# Saxo Readonly

[Français](README.fr.md) · [Configuration](docs/configuration.md) · [OpenClaw integration](docs/openclaw.md) · [Contributing](CONTRIBUTING.md)

A local, read-only Python connector for **Saxo Bank OpenAPI**, usable from a terminal, Python, or an optional OpenClaw skill. It reads portfolios, stores SQLite snapshots, and produces local reports and alerts. It has no runtime dependency outside the Python standard library.

This is an independent community project, not an official Saxo product. Version **0.1.0** is a refactoring of the original `saxo-openclaw-readonly-v1.0.zip`; see [migration notes](docs/migration.md).

## What it does

- Reads accounts, consolidated balances, individual positions, and net positions in SIM or LIVE.
- Handles OAuth authorization code authentication, PKCE S256, token renewal, and token rotation.
- Saves timestamped portfolio snapshots in SQLite; reads history and reports offline.
- Detects balance changes between comparable snapshots and daily instrument price changes when Saxo supplies them.
- Exposes the same connector independently of OpenClaw, with an optional [SKILL.md](skills/saxo-readonly/SKILL.md).

**Read-only is enforced by the connector's endpoint and HTTP-method allowlists.** It is not a claim that a stolen Saxo token would be restricted to reads. There is no trading, order management, transfer, or arbitrary HTTP command. The only POST requests are OAuth token requests. See the [security model](SECURITY.md).

## Install on Windows

Requirements: Python **3.10+**, Git, and a Saxo OpenAPI application registered for the environment you intend to use. Start with SIM. LIVE access depends on Saxo's application approval and account permissions; SIM and LIVE use different application credentials. [Saxo environments](https://www.developer.saxo/openapi/learn/environments).

Run in PowerShell:

```powershell
Set-Location C:\Users\eric\IdeaProjects
git clone https://github.com/evialle/saxo-readonly.git
Set-Location saxo-readonly
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\saxo-readonly.exe --help
```

If you already have the repository, start from `Set-Location saxo-readonly`. These commands do not require PowerShell virtual-environment activation. Other users can choose any parent directory.

Keep your configuration outside the repository:

```powershell
$saxoConfigDir = Join-Path $env:LOCALAPPDATA 'saxo-readonly'
New-Item -ItemType Directory -Force -Path $saxoConfigDir | Out-Null
Copy-Item .\config.env.example (Join-Path $saxoConfigDir 'config.env')
notepad (Join-Path $saxoConfigDir 'config.env')
$env:SAXO_CONFIG_FILE = Join-Path $saxoConfigDir 'config.env'
```

The environment variable above lasts for this terminal session. Set it again in a new terminal, or pass `--config PATH` before the command. Do not overwrite an existing configuration when repeating setup.

## Install on Linux or macOS

```bash
git clone https://github.com/evialle/saxo-readonly.git
cd saxo-readonly
python3 -m venv .venv
.venv/bin/python -m pip install .
install -d -m 700 "$HOME/.config/saxo-readonly"
install -m 600 config.env.example "$HOME/.config/saxo-readonly/config.env"
export SAXO_CONFIG_FILE="$HOME/.config/saxo-readonly/config.env"
```

Edit the copied configuration with your local editor. Use `.venv/bin/saxo-readonly` in place of the Windows executable below. Do not repeat `install` over an existing configuration.

## Authenticate

For a **PKCE application**, set your AppKey, leave AppSecret empty, and retain `SAXO_OAUTH_FLOW=pkce`. Register `http://localhost/callback` with Saxo; the runtime redirect is `http://localhost:8765/callback`. Saxo's PKCE registration uses a portless redirect, while the authorization request can include a port. A confidential application instead uses `SAXO_OAUTH_FLOW=code`, its AppSecret, and its registered redirect URI. [Saxo PKCE reference](https://www.developer.saxo/openapi/learn/oauth-authorization-code-grant-pkce).

```powershell
.\.venv\Scripts\saxo-readonly.exe auth-start
.\.venv\Scripts\saxo-readonly.exe auth-finish
.\.venv\Scripts\saxo-readonly.exe auth-status
```

1. Run `auth-start`, then open the printed authorization URL in your own browser.
2. Sign in to Saxo. The browser redirects to the configured callback URL. **This project does not run a local callback server**: a connection-refused page is expected. Copy the complete URL from the address bar.
3. Run `auth-finish` and paste that URL into its hidden terminal prompt. Never put it in a shell argument, issue, log, or agent conversation.

Run both steps on the same machine, under the same user and configuration. If an attempt expires or fails, start a new one. New API requests refresh tokens when needed. To keep an idle session renewed while a terminal stays open:

```powershell
.\.venv\Scripts\saxo-readonly.exe refresh --watch --interval 300
```

Renewal cannot guarantee a permanent login: Saxo may expire or revoke the session. A sleeping or disconnected PC cannot keep it alive. See [operations](docs/operations.md).

## Read and monitor

```powershell
.\.venv\Scripts\saxo-readonly.exe accounts
.\.venv\Scripts\saxo-readonly.exe balances
.\.venv\Scripts\saxo-readonly.exe positions
.\.venv\Scripts\saxo-readonly.exe netpositions
.\.venv\Scripts\saxo-readonly.exe snapshot
.\.venv\Scripts\saxo-readonly.exe history --limit 20
.\.venv\Scripts\saxo-readonly.exe report
.\.venv\Scripts\saxo-readonly.exe alerts --threshold 3 --fail-on-alert
```

`snapshot` collects current data and saves it locally. `history`, `report`, and `alerts` use saved snapshots without contacting Saxo. `report` emits Markdown; data commands emit JSON. Output can contain private account and portfolio information: share only what you intend to disclose.

An alert threshold is a strictly positive percentage. The balance comparison uses the latest snapshot and its compatible predecessor: same environment, client, currency, and account set. A zero baseline or missing value does not yield a percentage. Instrument alerts use Saxo's daily change field when available; missing prices are not zero changes.

**A balance delta is not an investment return.** Deposits, withdrawals, trading, dividends, fees, and exchange rates are not neutralized. Consolidated balances use Saxo's reported currency; do not add values from accounts with different currencies. Snapshots contain successive API reads, not an atomic market-wide valuation.

| Exit code | Meaning |
| --- | --- |
| `0` | Command completed; also used for empty history or no baseline |
| `1` | Configuration, authentication, API, or local-storage failure |
| `2` | Invalid command-line syntax |
| `3` | An alert triggered and `--fail-on-alert` was requested |
| `130` | Interrupted with Ctrl+C |

No email, chat message, or other external notification is sent by the connector. A scheduler can inspect JSON or exit code 3 and handle delivery under your control.

## Use as a Python library

```python
from saxo_readonly.client import SaxoClient
from saxo_readonly.config import Config

client = SaxoClient(Config.load())
balances = client.balances()
positions = client.positions()
portfolio = client.snapshot()  # Returns data; CLI snapshot also saves it to SQLite.
```

Authenticate first through the CLI. `Config.load()` reads the configuration selected by `SAXO_CONFIG_FILE` or an explicit `path`; environment variables take precedence over file values. See [configuration](docs/configuration.md) for storage and multiple profiles.

## OpenClaw is optional

The connector works without OpenClaw. To use it with an agent, install the Python package on the machine where that agent executes commands, make `saxo-readonly` available on its PATH, authenticate locally, then install only `skills/saxo-readonly`. Follow the [OpenClaw guide](docs/openclaw.md); copying the skill alone does not install the connector.

## Development and verification

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests use synthetic data and mocked network responses. They cover read-only restrictions, OAuth, pagination, storage, alerts, and CLI behavior. GitHub Actions runs the repository's CI configuration; it does not receive Saxo credentials. Offline tests do **not** prove live account access, Saxo entitlements, or end-to-end OAuth success for your application. See [CONTRIBUTING.md](CONTRIBUTING.md).

Licensed under [MIT](LICENSE). Contributions are welcome, including corrections to Saxo compatibility supported by reproducible SIM evidence with all personal data removed.
