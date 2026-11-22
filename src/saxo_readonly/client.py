"""Saxo portfolio reads, independent of OpenClaw or any agent runtime."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from .errors import ApiError, ReadOnlyViolation
from .transport import API_BASES, HttpTransport, validate_request


PAGE_SIZE = 100
MAX_PAGES = 100
MAX_ITEMS = 10000


class SaxoClient:
    """Expose a fixed set of portfolio reads; no generic write/trading interface."""

    def __init__(self, config, auth=None, transport=None):
        if config.api_base not in API_BASES:
            raise ReadOnlyViolation("Unsupported Saxo API base URL.")
        self.config = config
        self.transport = transport or HttpTransport()
        if auth is None:
            from .auth import AuthManager
            auth = AuthManager(config, transport=self.transport)
        self.auth = auth

    def _get(self, url: str) -> dict[str, Any]:
        validate_request("GET", url)
        # This extra check prevents a SIM session following a LIVE pagination URL.
        if not url.startswith(self.config.api_base):
            raise ReadOnlyViolation("Cross-environment API request refused.")
        token = self.auth.access_token()
        try:
            return self.transport.request("GET", url, headers={"Authorization": "Bearer " + token})
        except ApiError as exc:
            if exc.status_code != 401:
                raise
        token = self.auth.access_token(force_refresh=True)
        # One refresh/retry only. Persistent authorization failure is returned.
        return self.transport.request("GET", url, headers={"Authorization": "Bearer " + token})

    def _next_url(self, value: str, current: str, endpoint: str,
                  original_params: dict[str, Any]) -> str:
        if not isinstance(value, str) or value.startswith("//") or "\\" in value:
            raise ReadOnlyViolation("Unsafe pagination link refused.")
        # Query-only, absolute same-origin and root-relative links are supported.
        # Reject path traversal before urljoin can silently normalize it.
        raw_path = urlsplit(value).path
        if any(segment in (".", "..") for segment in raw_path.split("/")) or "%" in raw_path:
            raise ReadOnlyViolation("Unsafe pagination path refused.")
        url = urljoin(current, value)
        parsed = urlsplit(url)
        expected = urlsplit(self.config.api_base + endpoint)
        if (parsed.scheme, parsed.netloc, parsed.path) != (
            expected.scheme, expected.netloc, expected.path
        ):
            raise ReadOnlyViolation("Pagination must remain on the same endpoint and environment.")
        validate_request("GET", url)
        params = dict(parse_qsl(parsed.query))
        for key in ("FieldGroups", "$inlinecount"):
            if key in original_params:
                if key in params and params[key] != str(original_params[key]):
                    raise ReadOnlyViolation("Pagination changed the requested field selection.")
                params[key] = str(original_params[key])
        if "$skip" not in params:
            raise ApiError("Pagination link is missing an offset.")
        params.setdefault("$top", str(PAGE_SIZE))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), ""))

    def _collection(self, endpoint: str, fields: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"$top": PAGE_SIZE, "$skip": 0}
        if fields:
            params["FieldGroups"] = fields
        if endpoint == "port/v1/accounts/me":
            params["$inlinecount"] = "AllPages"
        url = self.config.api_base + endpoint + "?" + urlencode(params)
        rows: list[dict[str, Any]] = []
        offsets: set[int] = set()
        for _ in range(MAX_PAGES):
            query = dict(parse_qsl(urlsplit(url).query))
            offset = int(query.get("$skip", "0"))
            if offset in offsets or (offsets and offset <= max(offsets)):
                raise ApiError("Repeated or backwards Saxo pagination offset.")
            offsets.add(offset)
            page = self._get(url)
            batch = page.get("Data")
            if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
                raise ApiError("Invalid Saxo collection response.")
            rows.extend(batch)
            if len(rows) > MAX_ITEMS:
                raise ApiError("Saxo collection exceeded the item limit.")
            count = page.get("__count")
            if count is not None and (type(count) is not int or count < 0):
                raise ApiError("Invalid Saxo collection count.")
            next_link = page.get("__next")
            if next_link:
                if not batch:
                    raise ApiError("Empty Saxo page has a continuation link.")
                next_url = self._next_url(next_link, url, endpoint, params)
                next_offset = int(dict(parse_qsl(urlsplit(next_url).query))["$skip"])
                if next_offset != offset + len(batch):
                    raise ApiError("Saxo pagination would omit or repeat rows.")
                url = next_url
                continue
            if count is not None and len(rows) < count:
                if not batch:
                    raise ApiError("Saxo collection ended before its reported count.")
            elif count is not None or len(batch) < int(query.get("$top", PAGE_SIZE)):
                return rows
            params["$skip"] = offset + len(batch)
            url = self.config.api_base + endpoint + "?" + urlencode(params)
        raise ApiError("Saxo collection exceeded the page limit; no partial result returned.")

    def client_details(self) -> dict[str, Any]:
        return self._get(self.config.api_base + "port/v1/clients/me")

    def accounts(self) -> list[dict[str, Any]]:
        return self._collection("port/v1/accounts/me")

    def balances(self) -> dict[str, Any]:
        """Return Saxo's aggregate in client currency; never sum mixed currencies."""
        return self._get(self.config.api_base + "port/v1/balances/me")

    def positions(self) -> list[dict[str, Any]]:
        return self._collection("port/v1/positions/me", "PositionBase,PositionView,DisplayAndFormat")

    def netpositions(self) -> list[dict[str, Any]]:
        return self._collection("port/v1/netpositions/me", "NetPositionBase,NetPositionView,DisplayAndFormat")

    def snapshot(self) -> dict[str, Any]:
        """Fetch a complete sample. The API reads are sequential, not atomic."""
        identity = self.client_details()
        client_key = identity.get("ClientKey")
        if not isinstance(client_key, str) or not client_key:
            raise ApiError("Saxo client identity is missing; snapshot refused.")
        accounts = self.accounts()
        if any(a.get("ClientKey", client_key) != client_key for a in accounts):
            raise ApiError("Saxo account identity changed; snapshot refused.")
        balances = self.balances()
        currency, total = balances.get("Currency"), balances.get("TotalValue")
        if not isinstance(currency, str) or not currency.strip():
            raise ApiError("Saxo reporting currency is missing; snapshot refused.")
        if isinstance(total, bool) or not isinstance(total, (int, float)) or not math.isfinite(total):
            raise ApiError("Saxo total value is invalid; snapshot refused.")
        if balances.get("CalculationReliability", "Ok") != "Ok":
            raise ApiError("Saxo balance calculation is unreliable; snapshot refused.")
        positions = self.positions()
        netpositions = self.netpositions()
        if self.client_details().get("ClientKey") != client_key:
            raise ApiError("Saxo client identity changed during collection; snapshot refused.")
        return {
            "environment": self.config.env,
            "client_key": client_key,
            "currency": currency,
            "total_value": total,
            "accounts": accounts,
            "balances": balances,
            "positions": positions,
            "netpositions": netpositions,
            "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
