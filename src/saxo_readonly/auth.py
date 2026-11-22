"""Saxo OAuth authorization code and PKCE, with rotating refresh tokens."""

from __future__ import annotations

import base64
import hashlib
import math
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from ._secrets import read_json, session_lock, write_json
from .config import Config
from .errors import ApiError, AuthError

PENDING_TTL = 600
REFRESH_MARGIN = 120


def _positive_seconds(value) -> float:
    if isinstance(value, bool):
        raise AuthError("Saxo returned an invalid token expiry.")
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        raise AuthError("Saxo returned an invalid token expiry.") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise AuthError("Saxo returned an invalid token expiry.")
    return seconds


class AuthManager:
    """Manage one application's session. Token values are never printed."""

    def __init__(self, config: Config, transport=None):
        self.config = config
        if transport is None:
            from .transport import HttpTransport
            transport = HttpTransport()
        self.transport = transport

    @property
    def _pending_file(self):
        return self.config.data_dir / "auth-pending.json"

    def start(self) -> str:
        self.config.require_auth()
        state = secrets.token_urlsafe(32)
        pending = {"state": state, "created_at": time.time(), "binding": self.config.binding}
        query = {"response_type": "code", "client_id": self.config.app_key,
                 "redirect_uri": self.config.redirect_uri, "state": state}
        if self.config.flow == "pkce":
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
            pending["code_verifier"] = verifier
            query.update(code_challenge=challenge, code_challenge_method="S256")
        with session_lock(self.config.data_dir):
            write_json(self._pending_file, pending)
        return self.config.auth_base + "/authorize?" + urlencode(query)

    def _check_binding(self, data: dict) -> None:
        if data.get("binding") != self.config.binding:
            raise AuthError("Saved session belongs to another app, environment or redirect configuration; authenticate again.")

    def _exchange(self, form: dict) -> dict:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if self.config.flow == "code":
            credentials = f"{self.config.app_key}:{self.config.app_secret}".encode("utf-8")
            headers["Authorization"] = "Basic " + base64.b64encode(credentials).decode("ascii")
        else:
            form = {**form, "client_id": self.config.app_key}
        try:
            return self.transport.request("POST", self.config.auth_base + "/token",
                                          headers=headers, data=urlencode(form).encode("ascii"))
        except ApiError as exc:
            if exc.status_code in (400, 401, 403):
                raise AuthError("Saxo rejected authentication or token renewal; run auth-start and auth-finish again.") from None
            raise AuthError("Token request failed. Do not retry a consumed authorization code; authenticate again if renewal fails.") from None

    def _normalize(self, response: dict, *, previous: dict | None = None, verifier: str = "") -> dict:
        if not isinstance(response, dict):
            raise AuthError("Saxo returned an invalid token response.")
        access = response.get("access_token")
        refresh = response.get("refresh_token")
        if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
            raise AuthError("Saxo did not return both access and refresh tokens; authenticate again.")
        if any(c.isspace() or ord(c) < 32 for c in access + refresh):
            raise AuthError("Saxo returned an invalid token value.")
        token_type = response.get("token_type", "Bearer")
        if not isinstance(token_type, str) or token_type.lower() != "bearer":
            raise AuthError("Saxo returned an unsupported token type.")
        now = time.time()
        access_expiry = now + _positive_seconds(response.get("expires_in"))
        refresh_ttl = response.get("refresh_token_expires_in")
        # Missing refresh expiry is unknown, not an arbitrary hardcoded lifetime.
        refresh_expiry = now + _positive_seconds(refresh_ttl) if refresh_ttl is not None else None
        return {"binding": self.config.binding, "access_token": access, "refresh_token": refresh,
                "access_expires_at": access_expiry, "refresh_expires_at": refresh_expiry,
                "code_verifier": verifier or (previous or {}).get("code_verifier", ""),
                "updated_at": now}

    def finish(self, callback_url: str) -> None:
        self.config.require_auth()
        if not isinstance(callback_url, str) or len(callback_url) > 16384 or any(c.isspace() or ord(c) < 32 for c in callback_url):
            raise AuthError("Invalid callback URL.")
        try:
            callback = urlsplit(callback_url)
            expected = urlsplit(self.config.redirect_uri)
            params = parse_qs(callback.query, keep_blank_values=True, max_num_fields=20)
        except ValueError:
            raise AuthError("Invalid callback URL.") from None
        if callback.fragment or (callback.scheme, callback.netloc, callback.path) != (expected.scheme, expected.netloc, expected.path):
            raise AuthError("Callback URL does not match the configured redirect URI.")
        if "error" in params:
            raise AuthError("Saxo authorization was declined; start authorization again.")
        if any(len(params.get(key, [])) != 1 or not params[key][0] for key in ("state", "code")):
            raise AuthError("Callback must contain exactly one non-empty code and state.")
        with session_lock(self.config.data_dir):
            pending = read_json(self._pending_file)
            self._check_binding(pending)
            try:
                age = time.time() - float(pending["created_at"])
            except (KeyError, TypeError, ValueError):
                raise AuthError("Invalid pending authorization; run auth-start again.") from None
            if not math.isfinite(age) or not 0 <= age <= PENDING_TTL:
                raise AuthError("Authorization request expired; run auth-start again.")
            stored_state = pending.get("state")
            if not isinstance(stored_state, str) or not secrets.compare_digest(params["state"][0].encode("utf-8"), stored_state.encode("utf-8")):
                raise AuthError("OAuth state does not match; callback rejected.")
            form = {"grant_type": "authorization_code", "code": params["code"][0], "redirect_uri": self.config.redirect_uri}
            verifier = pending.get("code_verifier", "")
            if self.config.flow == "pkce":
                if not isinstance(verifier, str) or not 43 <= len(verifier) <= 128:
                    raise AuthError("PKCE verifier missing; run auth-start again.")
                form["code_verifier"] = verifier
            # Consume before network exchange: ambiguous failures must not replay codes.
            self._pending_file.unlink()
            tokens = self._normalize(self._exchange(form), verifier=verifier)
            write_json(self.config.tokens_file, tokens)

    def _tokens(self) -> dict:
        tokens = read_json(self.config.tokens_file)
        self._check_binding(tokens)
        if not all(isinstance(tokens.get(k), str) and tokens[k] for k in ("access_token", "refresh_token")):
            raise AuthError("Session is incomplete; authenticate again.")
        if any(c.isspace() or ord(c) < 32 for c in tokens["access_token"] + tokens["refresh_token"]):
            raise AuthError("Session token is invalid; authenticate again.")
        for key in ("access_expires_at", "refresh_expires_at"):
            value = tokens.get(key)
            if key == "refresh_expires_at" and value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise AuthError("Session expiry is invalid; authenticate again.")
        return tokens

    def access_token(self, force_refresh: bool = False) -> str:
        self.config.require_auth()
        with session_lock(self.config.data_dir):
            tokens = self._tokens()
            now = time.time()
            refresh_expiry = tokens.get("refresh_expires_at")
            needs_refresh = force_refresh or tokens["access_expires_at"] <= now + REFRESH_MARGIN
            needs_refresh = needs_refresh or (refresh_expiry is not None and refresh_expiry <= now + REFRESH_MARGIN)
            if not needs_refresh:
                return tokens["access_token"]
            if refresh_expiry is not None and refresh_expiry <= now:
                raise AuthError("Refresh token expired; run auth-start and auth-finish again.")
            form = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}
            if self.config.flow == "pkce":
                verifier = tokens.get("code_verifier")
                if not isinstance(verifier, str) or not verifier:
                    raise AuthError("PKCE verifier missing; authenticate again.")
                form["code_verifier"] = verifier
            renewed = self._normalize(self._exchange(form), previous=tokens)
            write_json(self.config.tokens_file, renewed)
            return renewed["access_token"]

    def refresh(self) -> None:
        self.access_token(force_refresh=True)

    def status(self) -> dict:
        if not self.config.tokens_file.exists():
            return {"authenticated": False, "environment": self.config.env}
        with session_lock(self.config.data_dir):
            tokens = self._tokens()
            now = time.time()
            refresh_expiry = tokens.get("refresh_expires_at")
            return {"authenticated": tokens["access_expires_at"] > now,
                    "environment": self.config.env,
                    "access_expires_at": tokens["access_expires_at"],
                    "refresh_expires_at": refresh_expiry,
                    "refresh_available": refresh_expiry is None or refresh_expiry > now}
