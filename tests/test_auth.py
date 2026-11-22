import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

from saxo_readonly.auth import AuthManager
from saxo_readonly.config import Config
from saxo_readonly.errors import ApiError, AuthError
from saxo_readonly._secrets import read_json, session_lock, write_json


class TokenTransport:
    def __init__(self):
        self.calls = []
        self.reply = {"access_token": "test-access", "refresh_token": "test-refresh",
                      "expires_in": 1200, "refresh_token_expires_in": 2400, "token_type": "Bearer"}

    def request(self, method, url, *, headers=None, data=None):
        self.calls.append((method, url, headers, parse_qs(data.decode("ascii"))))
        if isinstance(self.reply, Exception):
            raise self.reply
        return dict(self.reply)


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cfg = Config(app_key="test-client", data_dir=Path(self.directory.name))
        self.transport = TokenTransport()
        self.auth = AuthManager(self.cfg, self.transport)

    def callback(self):
        start = self.auth.start()
        state = parse_qs(urlsplit(start).query)["state"][0]
        return self.cfg.redirect_uri + "?" + urlencode({"code": "test-code", "state": state})

    def authenticate(self):
        self.auth.finish(self.callback())

    def test_pkce_s256_exchange_and_refresh_reuses_verifier(self):
        url = self.auth.start()
        query = parse_qs(urlsplit(url).query)
        pending = read_json(self.cfg.data_dir / "auth-pending.json")
        verifier = pending["code_verifier"]
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(query["code_challenge"], [expected])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertNotIn("scope", query)
        self.auth.finish(self.cfg.redirect_uri + "?" + urlencode({"code": "example", "state": query["state"][0]}))
        self.transport.reply["access_token"] = "rotated-access"
        self.transport.reply["refresh_token"] = "rotated-refresh"
        self.auth.refresh()
        form = self.transport.calls[-1][3]
        self.assertEqual(form["code_verifier"], [verifier])
        self.assertEqual(form["refresh_token"], ["test-refresh"])
        self.assertEqual(read_json(self.cfg.tokens_file)["refresh_token"], "rotated-refresh")
        self.assertEqual(self.auth.access_token(), "rotated-access")
        self.assertEqual(len(self.transport.calls), 2)

    def test_state_mismatch_and_duplicate_code_never_exchange(self):
        callback = self.callback()
        for invalid in (callback.replace("state=", "state=bad"), callback + "&code=second"):
            with self.assertRaises(AuthError):
                self.auth.finish(invalid)
        self.assertEqual(self.transport.calls, [])

    def test_wrong_redirect_and_unicode_state_never_exchange(self):
        callback = self.callback()
        for invalid in (callback.replace("localhost", "evil.example"), callback + "#bad",
                        self.cfg.redirect_uri + "?code=example&state=%C3%A9"):
            with self.assertRaises(AuthError):
                self.auth.finish(invalid)
        self.assertEqual(self.transport.calls, [])

    def test_expired_pending_request_is_rejected(self):
        callback = self.callback()
        path = self.cfg.data_dir / "auth-pending.json"
        pending = read_json(path)
        pending["created_at"] = time.time() - 601
        write_json(path, pending)
        with self.assertRaises(AuthError):
            self.auth.finish(callback)
        self.assertEqual(self.transport.calls, [])

    def test_pending_is_single_use_even_after_network_failure(self):
        callback = self.callback()
        self.transport.reply = ApiError("hidden upstream body", status_code=503)
        with self.assertRaises(AuthError) as caught:
            self.auth.finish(callback)
        self.assertNotIn("hidden", str(caught.exception))
        with self.assertRaises(AuthError):
            self.auth.finish(callback)
        self.assertEqual(len(self.transport.calls), 1)

    def test_code_flow_uses_basic_auth(self):
        self.cfg = Config(app_key="test-client", app_secret="test-secret", flow="code", data_dir=Path(self.directory.name))
        self.auth = AuthManager(self.cfg, self.transport)
        self.authenticate()
        call = self.transport.calls[0]
        self.assertEqual(base64.b64decode(call[2]["Authorization"].split()[1]).decode(), "test-client:test-secret")
        self.assertNotIn("code_verifier", call[3])

    def test_changed_app_cannot_use_saved_session(self):
        self.authenticate()
        changed = Config(app_key="another-app", data_dir=Path(self.directory.name))
        with self.assertRaises(AuthError):
            AuthManager(changed, self.transport).access_token()
        self.assertEqual(len(self.transport.calls), 1)

    def test_expired_refresh_fails_without_request(self):
        self.authenticate()
        tokens = read_json(self.cfg.tokens_file)
        tokens["refresh_expires_at"] = time.time() - 1
        write_json(self.cfg.tokens_file, tokens)
        with self.assertRaises(AuthError):
            self.auth.refresh()
        self.assertEqual(len(self.transport.calls), 1)

    def test_unknown_refresh_expiry_is_not_invented(self):
        del self.transport.reply["refresh_token_expires_in"]
        self.authenticate()
        self.assertIsNone(self.auth.status()["refresh_expires_at"])
        self.auth.refresh()
        self.assertEqual(len(self.transport.calls), 2)

    def test_invalid_token_response_not_saved(self):
        self.transport.reply["expires_in"] = float("nan")
        with self.assertRaises(AuthError):
            self.authenticate()
        self.assertFalse(self.cfg.tokens_file.exists())

    def test_status_never_contains_tokens(self):
        self.assertFalse(self.auth.status()["authenticated"])
        self.authenticate()
        status = json.dumps(self.auth.status())
        self.assertNotIn("test-access", status)
        self.assertNotIn("test-refresh", status)
        self.assertNotIn("code_verifier", status)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_windows_session_is_encrypted_at_rest(self):
        self.authenticate()
        raw = self.cfg.tokens_file.read_text()
        self.assertIn("windows-dpapi", raw)
        self.assertNotIn("test-access", raw)
        self.assertNotIn("test-refresh", raw)

    @unittest.skipIf(os.name == "nt", "POSIX mode permissions")
    def test_posix_session_permissions(self):
        self.authenticate()
        self.assertEqual(self.cfg.tokens_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.cfg.data_dir.stat().st_mode & 0o777, 0o700)

    def test_second_process_cannot_enter_locked_session(self):
        code = (
            "from pathlib import Path; import sys; "
            "from saxo_readonly._secrets import session_lock; "
            "from saxo_readonly.errors import AuthError\n"
            "try:\n"
            " with session_lock(Path(sys.argv[1]), timeout=0.15): sys.exit(2)\n"
            "except AuthError: sys.exit(0)\n"
        )
        with session_lock(self.cfg.data_dir):
            result = subprocess.run([sys.executable, "-c", code, str(self.cfg.data_dir)],
                                    capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
