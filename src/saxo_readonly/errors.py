"""Public exceptions; messages must never contain credentials or HTTP bodies."""


class SaxoError(Exception):
    """Base error suitable for displaying to a CLI user."""


class ConfigError(SaxoError):
    """Invalid local configuration."""


class AuthError(SaxoError):
    """Authentication or session storage failure."""


class ApiError(SaxoError):
    """A safe HTTP error without response bodies, URLs or request headers."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ReadOnlyViolation(SaxoError):
    """An operation fell outside the read-only connector's allowlist."""
