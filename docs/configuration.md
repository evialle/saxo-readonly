# Configuration and authentication

[English README](../README.md) · [README français](../README.fr.md)

## Files and precedence

Use `saxo-readonly --config PATH COMMAND` or the `SAXO_CONFIG_FILE` environment variable to select a configuration file. Without either, the default is:

| Platform | Default configuration |
| --- | --- |
| Windows | `%LOCALAPPDATA%\saxo-readonly\config.env` |
| Linux/macOS | `$XDG_CONFIG_HOME/saxo-readonly/config.env`, or `~/.config/saxo-readonly/config.env` |

The format is plain `KEY=value`, one setting per line, with `#` comment lines. It is data, not a shell script. Environment values override matching file settings. The connector does not execute the file or expand arbitrary shell expressions.

Copy [config.env.example](../config.env.example) to the selected location and edit locally. Never include credentials in a command-line argument or commit a real configuration. Offline history commands can run without an AppKey; network authentication requires a valid application configuration.

| Setting | Meaning | Default |
| --- | --- | --- |
| `SAXO_CONFIG_FILE` | Configuration file selection | Platform path above |
| `SAXO_ENV` | `SIM` or `LIVE` | `SIM` |
| `SAXO_APP_KEY` | Saxo application's AppKey / OAuth client ID | Empty |
| `SAXO_APP_SECRET` | AppSecret for confidential `code` flow | Empty |
| `SAXO_OAUTH_FLOW` | `pkce` or `code` | `pkce` |
| `SAXO_REDIRECT_URI` | Runtime callback URL | `http://localhost:8765/callback` |
| `SAXO_DATA_DIR` | Private storage root; environment suffix added automatically | Platform path below |

Alert thresholds are CLI options, e.g. `alerts --threshold 3`, not `SAXO_THRESHOLD_PCT` configuration. Unknown or legacy values must not be assumed to affect the program.

## Storage

| Platform | Default data directory |
| --- | --- |
| Windows | `%LOCALAPPDATA%\saxo-readonly\sim` or `...\live` |
| Linux/macOS | `$XDG_DATA_HOME/saxo-readonly/sim` or `.../live`; fallback `~/.local/share/saxo-readonly/...` |

`SAXO_DATA_DIR` replaces the root, not the final environment directory. Keep the root on a private local filesystem, outside the source tree and cloud synchronization folders. It contains the token session, pending authorization state, a process lock, and `history.sqlite3`.

On Windows, OAuth token and pending-state contents are protected for the current Windows user with DPAPI. The configuration and portfolio history are not encrypted by the application. On POSIX, secret files use mode `0600` and private directories use `0700`. Use OS account permissions and disk encryption where appropriate; another program running as your user can access your data. See [SECURITY.md](../SECURITY.md).

Session metadata is tied to the environment, application, callback, and OAuth flow. Changing these requires a new login. For separate applications or people, use separate configuration files **and separate `SAXO_DATA_DIR` roots**; changing only `--config` does not create a separate storage profile.

## PKCE application

Register your own native/public PKCE application with Saxo. Use its AppKey and no AppSecret. The connector generates a high-entropy verifier, sends an S256 challenge, checks the callback state and redirect, and retains the verifier for renewal. Saxo's PKCE flow does not use an OAuth `scope` parameter. [Official PKCE specification](https://www.developer.saxo/openapi/learn/oauth-authorization-code-grant-pkce).

With the provided default, register **`http://localhost/callback`** without a port. Requests use **`http://localhost:8765/callback`**. The browser may show an error page after redirection because this connector uses manual callback capture, not a local HTTP listener. Use the complete address-bar URL with `auth-finish`'s hidden prompt.

Authentication should be performed in a private terminal by the account owner. The authorization and callback URLs should not be pasted into an agent conversation. `auth-finish` accepts no URL argument, preventing accidental shell-history capture. Complete a pending attempt promptly; restart `auth-start` after an expired attempt.

## Confidential application

If Saxo registered your application for confidential authorization-code flow, set `SAXO_OAUTH_FLOW=code` and both AppKey and AppSecret. Use the redirect URI registered for that application. Do not distribute the AppSecret in a skill, repository, package, binary, or sample configuration. Each installation must supply its own application configuration. [Saxo authorization-code flow](https://www.developer.saxo/openapi/learn/oauth-authorization-code-grant).

## SIM and LIVE

| Purpose | SIM | LIVE |
| --- | --- | --- |
| API base | `https://gateway.saxobank.com/sim/openapi/` | `https://gateway.saxobank.com/openapi/` |
| Authorization base | `https://sim.logonvalidation.net` | `https://live.logonvalidation.net` |

These are fixed by the program; configuration does not accept an arbitrary API host. Register and authenticate separately in each environment. Switching `SAXO_ENV` selects a different data subdirectory. A successful SIM run does not grant LIVE access. [Saxo environments](https://www.developer.saxo/openapi/learn/environments).

## Renewal

API commands refresh a session when required. `refresh` requests renewal once, and `refresh --watch --interval 300` repeats it in the foreground. The interval is in seconds. Keep it shorter than the actual refresh-token lifetime; expiry timestamps come from the server, not a hard-coded promise about session duration.

Renewals are serialized across local processes so two commands do not concurrently consume a rotating refresh token. The new session replaces the saved one atomically. This does not prevent Saxo from requiring another interactive login. After an invalid/expired refresh token or an ambiguous network failure during renewal, authenticate again if retrying the command cannot restore the session. Do not repeatedly retry authentication failures indefinitely.
