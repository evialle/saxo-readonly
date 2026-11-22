"""Fail CI on tracked credentials/data or recognizable credential strings.

This is a supplemental guard, not an exhaustive secret detector. It never prints
the matching contents. Generated fixture credentials in tests are synthetic.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BAD_NAME = re.compile(
    r"(^|/)(?:\.env(?:\..*)?|tokens[^/]*\.json|auth-pending[^/]*\.json|config\.env)$"
    r"|\.(?:sqlite\w*|db|pem|key|pfx|p12|dpapi)$", re.I
)
SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    r"|\bgh[pousr]_[A-Za-z0-9]{30,}\b"
    r"|\bgithub_pat_[A-Za-z0-9_]{40,}\b"
    r"|\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"
    r"|(?im:^[ \t]*SAXO_APP_(?:KEY|SECRET)[ \t]*=[ \t]*[^\s#]+)"
)


def main() -> int:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    problems = []
    for name in filter(None, tracked):
        if BAD_NAME.search(name) and not name.endswith(".example"):
            problems.append(f"Private file must not be tracked: {name}")
        content = (ROOT / name).read_text(encoding="utf-8", errors="replace")
        if SECRET.search(content):
            problems.append(f"Possible credential in: {name}")
    print("\n".join(problems) if problems else "Tracked-file privacy checks passed.")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
