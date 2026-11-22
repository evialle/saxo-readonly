"""Private, atomic session files and native interprocess locking.

Windows encrypts session contents for the current user with DPAPI. POSIX uses
owner-only permissions. This does not protect against malicious code running
as the same user; keep the configured data directory in a trusted local path.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import tempfile
import time

from .errors import AuthError

MAX_SECRET_BYTES = 128 * 1024


def _windows_private_directory(path: Path) -> None:
    """Replace inherited directory permissions with user + SYSTEM full control."""
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                         wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [ctypes.c_wchar_p,
        wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    advapi.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    advapi.SetNamedSecurityInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_int, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi.SetNamedSecurityInfoW.restype = wintypes.DWORD
    token = wintypes.HANDLE()
    sid_text = ctypes.c_wchar_p()
    descriptor = ctypes.c_void_p()
    try:
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            raise OSError
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise OSError
        # TOKEN_USER begins with SID_AND_ATTRIBUTES, whose first field is PSID.
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise OSError
        sddl = f"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{sid_text.value})"
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise OSError
        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        dacl = ctypes.c_void_p()
        if not advapi.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise OSError
        # SE_FILE_OBJECT=1; DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION.
        if advapi.SetNamedSecurityInfoW(str(path), 1, 0x80000004, None, None, dacl, None):
            raise OSError
    except OSError:
        raise AuthError("Cannot restrict Windows session directory permissions.") from None
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        if sid_text:
            kernel.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
        if token:
            kernel.CloseHandle(token)


def secure_directory(path: Path) -> None:
    try:
        for ancestor in (path, *path.parents):
            if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
                raise AuthError("Session storage cannot use symbolic links or junctions.")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "nt":
            _windows_private_directory(path)
        else:
            if path.stat().st_uid != os.getuid():
                raise AuthError("Session directory must belong to the current user.")
            path.chmod(0o700)
    except OSError:
        raise AuthError("Cannot prepare private session directory.") from None


def _check_file(path: Path) -> None:
    if path.is_symlink():
        raise AuthError("Session files cannot be symbolic links.")
    if path.exists():
        stat = path.stat()
        if not path.is_file():
            raise AuthError("Session storage must be a regular file.")
        if os.name != "nt" and (stat.st_uid != os.getuid() or stat.st_mode & 0o077):
            raise AuthError("Session file must belong to the current user with permissions 600.")


def _dpapi(data: bytes, *, encrypt: bool) -> bytes:
    """Use the current Windows logon user's DPAPI key, with UI forbidden."""
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise AuthError("Windows could not protect or unlock the session; authenticate again as the original Windows user.")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def read_json(path: Path) -> dict:
    try:
        _check_file(path)
        with path.open("rb") as stream:
            raw = stream.read(MAX_SECRET_BYTES + 1)
        if len(raw) > MAX_SECRET_BYTES:
            raise AuthError("Session file exceeds its size limit.")
        obj = json.loads(raw)
        if os.name == "nt":
            if not isinstance(obj, dict) or obj.get("protection") != "windows-dpapi":
                raise AuthError("Unprotected Windows session file; authenticate again.")
            obj = json.loads(_dpapi(base64.b64decode(obj["payload"], validate=True), encrypt=False))
        if not isinstance(obj, dict):
            raise ValueError
        return obj
    except FileNotFoundError:
        raise AuthError("No saved session. Run auth-start, then auth-finish.") from None
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        raise AuthError("Cannot read session file; authenticate again.") from None


def write_json(path: Path, data: dict) -> None:
    secure_directory(path.parent)
    temporary = None
    try:
        _check_file(path)
        raw = json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if os.name == "nt":
            raw = json.dumps({"protection": "windows-dpapi", "payload": base64.b64encode(_dpapi(raw, encrypt=True)).decode("ascii")}).encode("ascii")
        if len(raw) > MAX_SECRET_BYTES:
            raise AuthError("Session file exceeds its size limit.")
        fd, temporary = tempfile.mkstemp(prefix=".saxo-session-", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            if os.name != "nt":
                os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError):
        raise AuthError("Cannot save the private session file.") from None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def session_lock(directory: Path, timeout: float = 30.0):
    """Serialize refresh-token rotation across CLI processes on Windows/POSIX."""
    secure_directory(directory)
    path = directory / ".auth.lock"
    fd = None
    locked = False
    try:
        _check_file(path)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"0")
        deadline = time.monotonic() + timeout
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise AuthError("Another process is updating the session; retry shortly.") from None
                time.sleep(0.1)
        yield
    except OSError:
        raise AuthError("Cannot lock or update the local session.") from None
    finally:
        if fd is not None:
            try:
                if locked:
                    os.lseek(fd, 0, os.SEEK_SET)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
