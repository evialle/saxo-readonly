# Migration from the original OpenClaw archive

This repository is derived from the user's `saxo-openclaw-readonly-v1.0.zip`, originally packaged as `saxo-openclaw-package/`. The archive contains a Linux-oriented single-file connector at `saxo-readonly/scripts/saxo.py`, an OpenClaw skill, shell installers, examples, and tests. Repository version **0.1.0** starts a separate version sequence for the standalone library; it is not a claim that the archive was already a published Python distribution.

The refactor separates configuration, authentication, HTTP transport, portfolio access, persistence, alerts, and the CLI. It adds Windows-compatible local storage and locking, explicit Python packaging, a standalone command, bilingual documentation, contribution guidance, and CI.

## Deliberate changes

| Original archive | This repository |
| --- | --- |
| `python3 .../scripts/saxo.py COMMAND` | Installed `saxo-readonly COMMAND` or `python -m saxo_readonly COMMAND` |
| `~/.config/saxo-openclaw/config.env` | Platform-specific `saxo-readonly/config.env`; see [configuration](configuration.md) |
| `~/.local/share/saxo-openclaw/` | New `saxo-readonly` storage root, separated by SIM/LIVE |
| Confidential `code` flow by default | PKCE by default; confidential code flow remains available |
| `status` | `auth-status`; use `history` for saved snapshots |
| `run` | `snapshot`, followed by `report` |
| `keepalive` | `refresh`, or `refresh --watch --interval 300` |
| `SAXO_THRESHOLD_PCT` | `alerts --threshold 3` |
| `positions` described net positions | `positions` for individual positions; `netpositions` for aggregated positions |
| Bundled Linux installers and service scripts | Cross-platform package installation; explicit user-managed scheduling |

## Move safely

1. Keep the old archive and private data as a backup outside Git.
2. Stop any old renewal or reporting service before using a new session for the same application.
3. Install the new package and copy its example configuration into a new private file. Transfer settings manually; select the flow that matches the existing Saxo application.
4. Authenticate again. Do not copy the legacy token or pending-authorization files into the new data directory.
5. Capture a first SIM snapshot, inspect the report, then capture another to verify comparison behavior. Configure LIVE separately only after your application is approved for it.
6. Install the new skill directory and replace old scheduled commands with the new command names.

There is **no automatic import of the legacy SQLite schema**. Keep the old database for historical reference. The new database uses explicit identity and comparison boundaries; old and new samples are not silently combined. No credentials, private snapshots, or ZIP contents containing private settings should be published as migration examples.
