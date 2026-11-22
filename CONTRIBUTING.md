# Contributing

Thank you for helping maintain a small, inspectable Saxo read-only connector. Discussions and code may be in English or French. Keep the two READMEs aligned when changing installation or user-facing behavior.

## Local setup

Use Python 3.10 or newer and a virtual environment. On Windows, from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

On Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m unittest discover -s tests -v
```

Use the checks defined in [the CI workflow](.github/workflows/ci.yml) before proposing a change. Tests are offline and do not need a Saxo account. Never put Saxo credentials in GitHub Actions secrets merely to run this suite.

## Changes and tests

- Keep runtime dependencies limited to the Python standard library unless there is a clear, reviewed reason to change that policy.
- Preserve the HTTP-method and endpoint allowlists, strict pagination boundary, redirect refusal, and secret-safe diagnostics. New read endpoints need official documentation and rejection tests for unsupported requests.
- Use synthetic fixtures. Do not copy responses from a real portfolio into tests, even if access tokens were removed: names, client/account keys, instruments, and amounts may still be private.
- Test behavior where it matters: failed and repeated pagination, authentication expiry/rotation, callback validation, concurrent refresh, incomplete snapshots, and incompatible comparison scopes.
- Keep Windows and POSIX paths and storage behavior supported. Do not require Bash in the normal Windows install flow.
- Explain observable before/after behavior and any migration impact in the pull request. Include the checks run and their results.

The project intentionally does not submit orders, transfer money, or expose arbitrary HTTP execution. Proposals that need those capabilities belong in another project.

## Report an issue

Include OS, Python version, command name, relevant package version/commit, sanitized error text, and a minimal artificial example. State whether the behavior was observed in SIM or LIVE without identifying the account. Do not attach configuration files, tokens, callback URLs, financial history, or unredacted network traces.

For security-sensitive reports, follow [SECURITY.md](SECURITY.md). Do not publicly publish an exploit with real credentials or private account data.

## License

By submitting a contribution, you agree it may be distributed under this repository's [MIT license](LICENSE). Keep attribution for any reused code and describe its source and license in the pull request.
