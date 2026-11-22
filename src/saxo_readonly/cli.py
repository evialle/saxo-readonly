"""Console interface; callback URLs and tokens never belong in command arguments."""
from __future__ import annotations

import argparse
import getpass
import json
import math
import sys
import time
from pathlib import Path

from . import __version__
from .alerts import analyze, render_report
from .auth import AuthManager
from .client import SaxoClient
from .config import Config
from .errors import SaxoError
from .history import SnapshotStore


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Read-only Saxo OpenAPI and local portfolio history")
    root.add_argument("--version", action="version", version=f"saxo-readonly {__version__}")
    root.add_argument("--config", type=Path, help="Private KEY=value file; environment overrides it")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("auth-start", help="Print login URL and save a ten-minute PKCE/state request")
    commands.add_parser("auth-finish", help="Paste callback URL at a hidden local prompt")
    commands.add_parser("auth-status", help="Show local session expiry without exposing tokens")
    refresh = commands.add_parser("refresh", help="Renew OAuth session")
    refresh.add_argument("--watch", action="store_true", help="Keep refreshing in the foreground")
    refresh.add_argument("--interval", type=float, default=300, help="Watch seconds, 30 to 600")
    for name in ("accounts", "balances", "positions", "netpositions"):
        commands.add_parser(name, help=f"Fetch Saxo {name} (GET only)")
    commands.add_parser("snapshot", help="Fetch and atomically save a complete portfolio observation")
    history = commands.add_parser("history", help="Read saved observations without contacting Saxo")
    history.add_argument("--limit", type=int, default=20)
    for name in ("alerts", "report"):
        sub = commands.add_parser(name, help="Analyze the latest two saved observations, offline")
        sub.add_argument("--threshold", type=float, default=3.0, help="Positive percentage threshold")
        if name == "alerts":
            sub.add_argument("--fail-on-alert", action="store_true", help="Exit 3 when alerts trigger")
    return root


def _json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        cfg = Config.load(args.config)
        if args.command in ("history", "alerts", "report"):
            store = SnapshotStore(cfg.history_file)
            snapshots = store.recent(cfg.env, args.limit if args.command == "history" else 2)
            if args.command == "history":
                _json(snapshots)
            elif args.command == "report":
                print(render_report(snapshots, args.threshold))
            else:
                analysis = analyze(snapshots, args.threshold)
                _json(analysis)
                if args.fail_on_alert and analysis["triggered"]:
                    return 3
            return 0
        auth = AuthManager(cfg)
        if args.command == "auth-start":
            print(auth.start())
        elif args.command == "auth-finish":
            if not sys.stdin.isatty():
                raise SaxoError("Run auth-finish in an interactive local terminal.")
            auth.finish(getpass.getpass("Paste the full redirect URL (hidden): ").strip())
            _json({"authenticated": True, "environment": cfg.env})
        elif args.command == "auth-status":
            _json(auth.status())
        elif args.command == "refresh":
            if not math.isfinite(args.interval) or not 30 <= args.interval <= 600:
                raise SaxoError("Refresh interval must be between 30 and 600 seconds.")
            while True:
                auth.refresh()
                _json(auth.status())
                if not args.watch:
                    break
                sys.stdout.flush()
                time.sleep(args.interval)
        else:
            client = SaxoClient(cfg, auth=auth)
            if args.command == "snapshot":
                _json(SnapshotStore(cfg.history_file).save(client.snapshot()))
            else:
                _json(getattr(client, args.command)())
        return 0
    except SaxoError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError, ValueError):
        print("Error: local I/O or data failure; check configuration and file permissions.", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Stopped.", file=sys.stderr)
        return 130
