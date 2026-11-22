"""Bounded HTTPS transport with a deliberately small read-only request surface."""

from __future__ import annotations

import json
import re
import ssl
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .errors import ApiError, ReadOnlyViolation


API_BASES = (
    "https://gateway.saxobank.com/sim/openapi/",
    "https://gateway.saxobank.com/openapi/",
)
TOKEN_URLS = frozenset((
    "https://sim.logonvalidation.net/token",
    "https://live.logonvalidation.net/token",
))
ENDPOINT_PARAMETERS = {
    "port/v1/clients/me": frozenset(),
    "port/v1/accounts/me": frozenset(("$top", "$skip", "$inlinecount")),
    "port/v1/balances/me": frozenset(),
    "port/v1/positions/me": frozenset(("$top", "$skip", "FieldGroups")),
    "port/v1/netpositions/me": frozenset(("$top", "$skip", "FieldGroups")),
}
FIELD_GROUPS = {
    "port/v1/positions/me": frozenset(("PositionBase", "PositionView", "DisplayAndFormat")),
    "port/v1/netpositions/me": frozenset((
        "NetPositionBase", "NetPositionView", "DisplayAndFormat",
    )),
}


def validate_request(method: str, url: str, data: bytes | None = None) -> None:
    """Reject unknown operations before creating a request or obtaining a token."""
    if not isinstance(url, str) or any(ord(c) < 33 or ord(c) > 126 for c in url):
        raise ReadOnlyViolation("Invalid request URL.")
    if method == "POST":
        if url not in TOKEN_URLS or data is None:
            raise ReadOnlyViolation("POST is restricted to the Saxo OAuth token endpoint.")
        return
    if method != "GET" or data is not None:
        raise ReadOnlyViolation("Portfolio requests must use GET without a body.")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "gateway.saxobank.com" or parsed.fragment:
        raise ReadOnlyViolation("Only the fixed Saxo HTTPS API origin is allowed.")
    endpoint = None
    for base in API_BASES:
        base_path = urlsplit(base).path
        if parsed.path.startswith(base_path):
            endpoint = parsed.path[len(base_path):]
            break
    if endpoint not in ENDPOINT_PARAMETERS:
        raise ReadOnlyViolation("Endpoint is outside the portfolio read-only allowlist.")
    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True) if parsed.query else []
    except ValueError:
        raise ReadOnlyViolation("Invalid API query parameters.") from None
    params = dict(pairs)
    if len(params) != len(pairs) or set(params) - ENDPOINT_PARAMETERS[endpoint]:
        raise ReadOnlyViolation("Unsupported or duplicate API query parameter.")
    for name in ("$skip", "$top"):
        if name in params:
            value = params[name]
            if not re.fullmatch(r"[0-9]{1,8}", value):
                raise ReadOnlyViolation("Invalid pagination parameter.")
            number = int(value)
            if name == "$top" and not 1 <= number <= 1000:
                raise ReadOnlyViolation("Page size must be between 1 and 1000.")
    if "$inlinecount" in params and params["$inlinecount"] != "AllPages":
        raise ReadOnlyViolation("Unsupported count parameter.")
    if "FieldGroups" in params:
        groups = params["FieldGroups"].split(",")
        if not groups or set(groups) - FIELD_GROUPS.get(endpoint, frozenset()):
            raise ReadOnlyViolation("Unsupported portfolio field group.")


class NoRedirects(HTTPRedirectHandler):
    """Never forward OAuth credentials or bearer tokens after a redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ApiError("Saxo HTTP redirect refused.", status_code=code)


class HttpTransport:
    """HTTPS JSON transport. Only safe GET requests receive bounded retries."""

    def __init__(self, *, timeout: float = 20, max_body: int = 5 * 1024 * 1024,
                 attempts: int = 3, opener=None, sleep=None):
        if not 0 < timeout <= 120 or not 1 <= attempts <= 5 or max_body <= 0:
            raise ValueError("Invalid transport limits.")
        self.timeout = timeout
        self.max_body = max_body
        self.attempts = attempts
        self.opener = opener or build_opener(
            NoRedirects(), HTTPSHandler(context=ssl.create_default_context())
        )
        self.sleep = sleep or time.sleep

    def request(self, method: str, url: str, *, headers: dict[str, str] | None = None,
                data: bytes | None = None) -> dict[str, Any]:
        validate_request(method, url, data)
        request_headers = {"Accept": "application/json", "User-Agent": "saxo-readonly/1.0"}
        request_headers.update(headers or {})
        if any("\r" in str(v) or "\n" in str(v) for v in request_headers.values()):
            raise ApiError("Invalid request headers.")
        request = Request(url, data=data, headers=request_headers, method=method)
        attempts = self.attempts if method == "GET" else 1
        for attempt in range(attempts):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    status = response.getcode()
                    if status != 200:
                        raise ApiError("Unexpected Saxo HTTP response.", status_code=status)
                    body = response.read(self.max_body + 1)
                    if len(body) > self.max_body:
                        raise ApiError("Saxo response exceeded the size limit.")
                    result = json.loads(body)
                    if not isinstance(result, dict):
                        raise ApiError("Expected a JSON object from Saxo.")
                    return result
            except HTTPError as exc:
                code = exc.code
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                exc.close()
                if (code == 429 or 500 <= code <= 599) and attempt + 1 < attempts:
                    # A long server backoff should fail this invocation, not trigger
                    # retries sooner than Saxo requested or block a scheduler forever.
                    if retry_after.isdigit():
                        delay = int(retry_after)
                        if delay > 30:
                            raise ApiError("Saxo requested a longer retry delay; retry later.",
                                           status_code=code) from None
                    else:
                        delay = 2 ** attempt
                    self.sleep(delay)
                    continue
                raise ApiError(f"Saxo HTTP {code}; check session or retry later.",
                               status_code=code) from None
            except (URLError, TimeoutError, ssl.SSLError, OSError, ValueError) as exc:
                # Never include exception text, request URLs, headers or response bodies.
                if isinstance(exc, (ValueError, UnicodeError)):
                    raise ApiError("Saxo returned invalid JSON.") from None
                raise ApiError("Saxo HTTPS transport failed.") from None
        raise ApiError("Saxo request attempts exhausted.")
