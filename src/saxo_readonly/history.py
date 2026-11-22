"""Transactional local snapshots, with an explicit schema version."""
from __future__ import annotations

import contextlib
import json
import math
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from .errors import SaxoError


def validate_snapshot(snapshot: dict) -> None:
    if not isinstance(snapshot, dict):
        raise SaxoError("Snapshot must be an object.")
    for key in ("client_key", "currency", "captured_at"):
        if not isinstance(snapshot.get(key), str) or not snapshot[key].strip():
            raise SaxoError(f"Snapshot is missing {key}.")
    if snapshot.get("environment") not in ("SIM", "LIVE"):
        raise SaxoError("Invalid snapshot environment.")
    try:
        stamp = datetime.fromisoformat(snapshot["captured_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError
    except ValueError:
        raise SaxoError("Snapshot timestamp must include a timezone.") from None
    value = snapshot.get("total_value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SaxoError("Snapshot total_value must be a finite number.")
    for key in ("accounts", "positions", "netpositions"):
        if not isinstance(snapshot.get(key), list) or any(
            not isinstance(row, dict) for row in snapshot[key]
        ):
            raise SaxoError(f"Snapshot {key} must contain objects.")
    if not isinstance(snapshot.get("balances"), dict):
        raise SaxoError("Snapshot balances must be an object.")
    keys = [account.get("AccountKey") for account in snapshot["accounts"]]
    if any(not isinstance(key, str) or not key for key in keys) or len(keys) != len(set(keys)):
        raise SaxoError("Snapshot account identities are missing or duplicated.")


class SnapshotStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextlib.contextmanager
    def _open(self):
        from ._secrets import secure_directory as ensure_secure_dir

        ensure_secure_dir(self.path.parent)
        if self.path.is_symlink():
            raise SaxoError("Symbolic database paths are not allowed.")
        # Pre-create with private permissions before SQLite writes financial data.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        if os.name != "nt":
            self.path.chmod(0o600)
        try:
            with contextlib.closing(sqlite3.connect(self.path, timeout=10)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA busy_timeout=10000")
                connection.execute("PRAGMA journal_mode=DELETE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise SaxoError("Unsupported snapshot schema version.")
                if version == 0:
                    existing = connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                    if existing:
                        raise SaxoError("Legacy database detected; use a new history file.")
                    with connection:
                        connection.execute(
                            "CREATE TABLE snapshots (id INTEGER PRIMARY KEY, "
                            "environment TEXT NOT NULL, client_key TEXT NOT NULL, "
                            "captured_at TEXT NOT NULL, payload TEXT NOT NULL)"
                        )
                        connection.execute(
                            "CREATE INDEX snapshots_scope ON snapshots(environment, id DESC)"
                        )
                        connection.execute("PRAGMA user_version=1")
                yield connection
        except sqlite3.Error:
            raise SaxoError("Cannot access snapshot database; check its path and integrity.") from None

    def save(self, snapshot: dict) -> dict:
        validate_snapshot(snapshot)
        payload = {key: value for key, value in snapshot.items() if key != "id"}
        try:
            serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError):
            raise SaxoError("Snapshot contains invalid JSON values.") from None
        with self._open() as connection, connection:
            cursor = connection.execute(
                "INSERT INTO snapshots(environment,client_key,captured_at,payload) VALUES(?,?,?,?)",
                (payload["environment"], payload["client_key"], payload["captured_at"], serialized),
            )
            return {**payload, "id": cursor.lastrowid}

    def recent(self, environment: str, limit: int = 20) -> list[dict]:
        if environment not in ("SIM", "LIVE") or not 1 <= limit <= 1000:
            raise SaxoError("Choose SIM/LIVE and a history limit between 1 and 1000.")
        if not self.path.exists():
            return []
        with self._open() as connection:
            rows = connection.execute(
                "SELECT id,payload FROM snapshots WHERE environment=? ORDER BY id DESC LIMIT ?",
                (environment, limit),
            ).fetchall()
        result = []
        try:
            for row in rows:
                payload = json.loads(row["payload"])
                validate_snapshot(payload)
                result.append({**payload, "id": row["id"]})
        except (ValueError, TypeError):
            raise SaxoError("Invalid stored snapshot data.") from None
        return result
