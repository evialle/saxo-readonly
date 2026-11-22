# CLI and operations

The CLI is `saxo-readonly`; `python -m saxo_readonly` is equivalent when that Python environment contains the installed package. Global `--config PATH` precedes the subcommand.

## Commands

| Command | Reads Saxo | Writes local state | Output |
| --- | --- | --- | --- |
| `auth-start` | No; prints the browser URL | Pending authorization | Authorization URL |
| `auth-finish` | Exchanges code for tokens | Token session | Confirmation JSON |
| `auth-status` | No | No | Non-secret session status JSON |
| `refresh` | OAuth token endpoint | Rotated token session | Status JSON |
| `refresh --watch --interval 300` | Repeated OAuth renewal | Rotated token session | Status JSON |
| `accounts` | Accounts | May renew tokens | JSON |
| `balances` | Consolidated balance | May renew tokens | JSON |
| `positions` | Individual positions | May renew tokens | JSON |
| `netpositions` | Net positions | May renew tokens | JSON |
| `snapshot` | Client, accounts, balance, positions | SQLite snapshot; may renew tokens | JSON |
| `history --limit 20` | No | No portfolio mutation | JSON |
| `report` | No | No portfolio mutation | Markdown |
| `alerts --threshold 3` | No | No portfolio mutation | JSON |

Use `--help` on the program or a subcommand for the exact options supported by your installed version. Local reads may create an empty SQLite database on first use. Data commands include private portfolio information; avoid public logs or CI artifacts containing their output.

## Snapshot semantics

A snapshot preserves the returned portfolio data, capture time in UTC, environment, client identity, reporting currency, and total value. Collection is sequential. A failed API fetch does not produce a successful complete snapshot. Balance values come from the consolidated Saxo balance response, avoiding manual addition across currencies.

Reports compare the current snapshot with its compatible predecessor. A compatible baseline uses the same environment, client key, currency, and account set. Different profiles are not combined. Without a baseline, the report shows current data and explains that comparison is unavailable. Without snapshots, it asks you to run `snapshot`.

Alerts detect an absolute percentage change in either direction. A threshold of 3 means `>= 3%` or `<= -3%`; it does not mean a currency amount. Missing or non-finite data is not interpreted as zero. A zero starting balance prevents a percentage comparison. Daily instrument changes, when available, are distinct from changes since the previous snapshot and can be based on delayed market data.

The connector does not adjust for cash flows, trades, dividends, fees, splits, or FX. Reports describe **valuation changes**, not performance, realized profit, or a recommendation to trade.

## Schedule locally

No schedule is installed automatically. Choose a frequency appropriate to your use and Saxo's limits. Use the same OS user and profile that performed login, absolute paths, and private output locations.

For Windows Task Scheduler, a snapshot action can use:

```text
Program:
C:\Users\eric\IdeaProjects\saxo-readonly\.venv\Scripts\saxo-readonly.exe

Arguments:
--config "C:\Users\eric\AppData\Local\saxo-readonly\config.env" snapshot

Start in:
C:\Users\eric\IdeaProjects\saxo-readonly
```

Adjust user and installation paths. Configure tasks to avoid overlapping instances and run as the same user so Windows can decrypt the saved session. Capture only the output you need. A separate renewal process can use `refresh --watch --interval 300`, but a sleeping PC, expired session, or failed network call needs attention. Do not assume a once-daily snapshot keeps the OAuth session alive between days.

On Linux, a scheduler can call:

```bash
/absolute/path/saxo-readonly/.venv/bin/saxo-readonly --config /absolute/private/path/config.env snapshot
```

You may run `alerts --threshold 3 --fail-on-alert` after a successful snapshot. Exit 3 means a detected alert; exit 1 or 2 means a failure that must not be described as “no alert.” Notifications are the scheduler's responsibility. Avoid transmitting raw JSON unless you intend to expose its account identifiers and amounts.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Missing application configuration | Set AppKey and the correct flow in the chosen private config; check environment overrides |
| Browser callback connection refused | Expected with manual capture; copy the full address and complete `auth-finish` |
| Callback rejected | Restart `auth-start`; keep the same user, machine, environment, and redirect configuration |
| Session expired/revoked | Run a new interactive authentication; a renewal loop cannot restore revoked consent |
| HTTP 401 after renewal | Reauthenticate and confirm the selected environment/application |
| HTTP 403 | Check Saxo application/account entitlements; repeated retries do not add permission |
| HTTP 429 | Reduce frequency; GET retry handling is bounded, so wait before the next command |
| Empty history | Run `snapshot`; `report` and `alerts` do not fetch current values |
| No percentage comparison | Obtain two comparable snapshots with a nonzero valid baseline |
| Windows session cannot be decrypted | Use the original Windows user/machine, or authenticate afresh |
| Skill visible but command unavailable | Install the package and set PATH on the actual OpenClaw execution host |

Do not put tokens, callback URLs, raw balances, account identifiers, or your configuration into bug reports. Share the command name, sanitized error category, Python/OS versions, and an artificial reproducer.

## Backups and retention

`history.sqlite3` contains private financial history. Back it up while no snapshot writer is active, or use SQLite's backup API. Keep backups encrypted and outside the repository. Retention is user-managed in this release; the CLI has no automatic purge or old-schema importer. Token files are not portable credentials: especially on Windows, reauthenticate on another machine instead of copying them.
