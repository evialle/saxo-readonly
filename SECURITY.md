# Security model and reporting

## Read-only boundary

The connector restricts portfolio requests to its explicit GET endpoint allowlist. OAuth token exchange and renewal are separate POST operations against the selected Saxo authentication host. There is no generic URL/request command, trading implementation, order-management operation, or transfer operation.

This is a property of this implementation, not a security scope imposed on every possible use of a Saxo bearer token. Saxo's PKCE documentation does not define a `readonly` OAuth scope. Keep tokens confidential even when using this connector. Application permissions, account entitlements, Saxo controls, and host security remain relevant. [Saxo PKCE reference](https://www.developer.saxo/openapi/learn/oauth-authorization-code-grant-pkce).

The transport refuses HTTP redirects and checks pagination against the permitted host, environment path, endpoint, and query parameters. Retry limits apply to idempotent reads; authentication POST requests are not blindly retried after an ambiguous failure. Errors should not include response bodies, authorization headers, callback codes, or tokens.

## Local data

- Configuration and financial history are private data. Store them outside the checkout, outside shared folders, and outside unreviewed cloud backup/synchronization.
- Windows OAuth token/pending-state payloads use current-user DPAPI protection. This is not encryption of the SQLite database or config file and does not protect against malicious code running as the same Windows user.
- POSIX secret files use `0600` and private state directories use `0700`. Windows access control depends on the private user-profile location and its ACLs in addition to DPAPI. Do not assume Unix mode bits configure Windows ACLs.
- Atomic session writes and cross-process locking protect against partial files and concurrent refresh-token rotation. They do not make a compromised host safe.
- CLI output, especially raw account/position JSON and history, can expose private identifiers and amounts. Terminal logs and redirected reports require the same care as the database.
- `.gitignore` is a convenience, not a secret scanner. Review the staged changes before every public commit; ignored files can still be force-added.

Authentication belongs in a private terminal. Paste callback URLs only into the hidden `auth-finish` prompt. Do not include them in shell arguments, issue text, screenshots, or conversations with an agent.

## If credentials are exposed

Disconnect the application through Saxo's account application-access controls, rotate an exposed application secret where applicable, and establish a new session. Revoking application access prevents further refresh, but already-issued access tokens may remain valid until their expiry. Follow [Saxo's token invalidation guidance](https://openapi.help.saxo/hc/en-us/articles/4417696479761-How-can-I-invalidate-an-access-refresh-token).

Remove exposed material from published content and repository history as appropriate, but do not treat deletion as a substitute for revocation. Check backups and automation logs. Avoid posting the leaked material again while reporting the incident.

## Report a vulnerability

Use the repository's **Security → Report a vulnerability** option if private reporting is enabled. If it is unavailable, open an issue asking for a private reporting channel, without exploit details, secrets, or portfolio data. No private email address is designated by this project.

Include a minimal synthetic reproducer and the affected commit/version. Maintainers cannot promise a response time. Before the first stable release, fixes target the current `main` branch; previous generated archive versions are not maintained here.
