"""Configuration independent of any agent platform. No dotenv execution."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit

from .errors import ConfigError


def default_root() -> Path:
    """User-local storage; never defaults to the repository or current directory."""
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "saxo-readonly"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "saxo-readonly"


def default_config_file() -> Path:
    if os.name == "nt":
        return default_root() / "config.env"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "saxo-readonly" / "config.env"


def _read_env(path: Path) -> dict[str, str]:
    if path.is_symlink():
        raise ConfigError("Configuration must be a regular file, not a symbolic link.")
    try:
        if os.name != "nt" and path.stat().st_mode & 0o077:
            raise ConfigError("Configuration permissions are too broad; use chmod 600.")
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        raise ConfigError("Cannot read configuration file.") from None
    result = {}
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"Configuration line {number}: expected NAME=value.")
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name.startswith("SAXO_"):
            raise ConfigError(f"Configuration line {number}: unsupported setting name.")
        if value[:1] in ("'", '"'):
            if len(value) < 2 or value[-1] != value[0]:
                raise ConfigError(f"Configuration line {number}: unclosed quote.")
            value = value[1:-1]
        result[name] = value
    return result


@dataclass(frozen=True)
class Config:
    env: str = "SIM"
    app_key: str = field(default="", repr=False)
    app_secret: str = field(default="", repr=False)
    redirect_uri: str = "http://localhost:8765/callback"
    flow: str = "pkce"
    data_dir: Path = field(default_factory=default_root)

    def __post_init__(self) -> None:
        env = self.env.upper()
        flow = self.flow.lower()
        if env not in ("SIM", "LIVE"):
            raise ConfigError("SAXO_ENV must be SIM or LIVE.")
        if flow not in ("pkce", "code"):
            raise ConfigError("SAXO_OAUTH_FLOW must be pkce or code.")
        try:
            parsed = urlsplit(self.redirect_uri)
            _ = parsed.port
        except ValueError:
            raise ConfigError("Invalid OAuth redirect URI.") from None
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(c.isspace() or ord(c) < 32 for c in self.redirect_uri)
            or not (
                parsed.scheme == "https"
                or (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1"))
            )
        ):
            raise ConfigError("Redirect URI must use HTTPS or HTTP loopback, without query, fragment or credentials.")
        object.__setattr__(self, "env", env)
        object.__setattr__(self, "flow", flow)
        object.__setattr__(self, "data_dir", Path(self.data_dir).expanduser().absolute() / env.lower())

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        explicit = path is not None or bool(os.environ.get("SAXO_CONFIG_FILE"))
        source = Path(path or os.environ.get("SAXO_CONFIG_FILE", default_config_file())).expanduser()
        raw = _read_env(source) if explicit or source.exists() else {}
        names = ("SAXO_ENV", "SAXO_APP_KEY", "SAXO_APP_SECRET", "SAXO_REDIRECT_URI", "SAXO_OAUTH_FLOW", "SAXO_DATA_DIR")
        raw.update({key: os.environ[key] for key in names if key in os.environ})
        return cls(
            env=raw.get("SAXO_ENV", "SIM"),
            app_key=raw.get("SAXO_APP_KEY", ""),
            app_secret=raw.get("SAXO_APP_SECRET", ""),
            redirect_uri=raw.get("SAXO_REDIRECT_URI", "http://localhost:8765/callback"),
            flow=raw.get("SAXO_OAUTH_FLOW", "pkce"),
            data_dir=Path(raw.get("SAXO_DATA_DIR") or default_root()),
        )

    def require_auth(self) -> None:
        if not self.app_key or any(c.isspace() or ord(c) < 32 for c in self.app_key):
            raise ConfigError("Configure SAXO_APP_KEY before authenticating.")
        if self.flow == "code" and not self.app_secret:
            raise ConfigError("SAXO_APP_SECRET is required for the confidential code flow.")

    @property
    def api_base(self) -> str:
        prefix = "sim/" if self.env == "SIM" else ""
        return f"https://gateway.saxobank.com/{prefix}openapi/"

    @property
    def auth_base(self) -> str:
        return f"https://{self.env.lower()}.logonvalidation.net"

    @property
    def tokens_file(self) -> Path:
        return self.data_dir / "tokens.json"

    @property
    def history_file(self) -> Path:
        return self.data_dir / "history.sqlite3"

    @property
    def binding(self) -> str:
        value = "\n".join((self.env, self.app_key, self.redirect_uri, self.flow))
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
