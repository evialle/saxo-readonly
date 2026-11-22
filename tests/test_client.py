"""Offline request-boundary, pagination, transport and complete-snapshot tests."""

from __future__ import annotations

import io
import unittest
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from saxo_readonly.client import SaxoClient
from saxo_readonly.errors import ApiError, ReadOnlyViolation
from saxo_readonly.transport import HttpTransport, NoRedirects, validate_request


BASE = "https://gateway.saxobank.com/sim/openapi/"
TOKEN = "https://sim.logonvalidation.net/token"


class FakeAuth:
    def __init__(self):
        self.calls = []

    def access_token(self, force_refresh=False):
        self.calls.append(force_refresh)
        return "fixture-renewed" if force_refresh else "fixture-token"


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class Response(io.BytesIO):
    def getcode(self):
        return 200


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, **kwargs):
        self.calls.append((request, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return Response(response)


def http_error(code, retry_after=None):
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return HTTPError(BASE + "secret-path", code, "sensitive-message", headers,
                     io.BytesIO(b'{"access_token":"sensitive-body"}'))


def client(responses):
    transport, auth = FakeTransport(responses), FakeAuth()
    instance = SaxoClient(SimpleNamespace(env="SIM", api_base=BASE), auth, transport)
    return instance, transport, auth


class ReadOnlyBoundaryTests(unittest.TestCase):
    def test_only_known_gets_and_oauth_post(self):
        for name in ("clients", "accounts", "balances", "positions", "netpositions"):
            validate_request("GET", BASE + f"port/v1/{name}/me")
        validate_request("POST", TOKEN, b"grant_type=refresh_token")

    def test_write_methods_rejected_before_network(self):
        opener = FakeOpener([])
        transport = HttpTransport(opener=opener)
        for method in ("POST", "PUT", "DELETE", "PATCH", "get", "HEAD"):
            with self.subTest(method=method), self.assertRaises(ReadOnlyViolation):
                transport.request(method, BASE + "port/v1/accounts/me", data=b"{}")
        self.assertFalse(opener.calls)

    def test_host_path_and_query_attacks_rejected(self):
        urls = [
            "http://gateway.saxobank.com/sim/openapi/port/v1/accounts/me",
            "https://gateway.saxobank.com.evil.invalid/sim/openapi/port/v1/accounts/me",
            "https://user@gateway.saxobank.com/sim/openapi/port/v1/accounts/me",
            "https://gateway.saxobank.com:443/sim/openapi/port/v1/accounts/me",
            BASE + "trade/v2/orders",
            BASE + "port/v1/accounts/me/../subscriptions",
            BASE + "port/v1/accounts/%6de",
            BASE + "port/v1/accounts/me#fragment",
            BASE + "port/v1/accounts/me?$skip=1&$skip=2",
            BASE + "port/v1/accounts/me?$top=0",
            BASE + "port/v1/accounts/me?$top=1001",
            BASE + "port/v1/accounts/me?$skip=-1",
            BASE + "port/v1/accounts/me?callback=https://evil.invalid",
            BASE + "port/v1/balances/me?AccountKey=other",
            BASE + "port/v1/positions/me?FieldGroups=Unknown",
        ]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ReadOnlyViolation):
                validate_request("GET", url)

    def test_token_post_rejects_redirect_and_query_hosts(self):
        for url in (TOKEN + "?next=bad", TOKEN + "/", TOKEN.replace("https", "http"),
                    "https://evil.invalid/token"):
            with self.subTest(url=url), self.assertRaises(ReadOnlyViolation):
                validate_request("POST", url, b"code=fixture")

    def test_redirect_handler_never_follows(self):
        with self.assertRaises(ApiError) as caught:
            NoRedirects().redirect_request(None, None, 302, "secret", {}, "https://evil.invalid")
        self.assertEqual(caught.exception.status_code, 302)
        self.assertNotIn("secret", str(caught.exception))


class TransportTests(unittest.TestCase):
    def test_json_and_request_timeout(self):
        opener = FakeOpener([b'{"Data":[]}'])
        result = HttpTransport(opener=opener, timeout=8).request("GET", BASE + "port/v1/accounts/me")
        self.assertEqual(result, {"Data": []})
        self.assertEqual(opener.calls[0][1]["timeout"], 8)

    def test_retry_get_429_then_success(self):
        opener, delays = FakeOpener([http_error(429, "3"), b'{"Data":[]}']), []
        transport = HttpTransport(opener=opener, sleep=delays.append)
        self.assertEqual(transport.request("GET", BASE + "port/v1/accounts/me"), {"Data": []})
        self.assertEqual(delays, [3])

    def test_retry_server_failure_is_bounded(self):
        opener, delays = FakeOpener([http_error(503), http_error(503), http_error(503)]), []
        with self.assertRaises(ApiError) as caught:
            HttpTransport(opener=opener, sleep=delays.append).request("GET", BASE + "port/v1/accounts/me")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(delays, [1, 2])
        self.assertEqual(len(opener.calls), 3)

    def test_long_retry_after_does_not_retry_early(self):
        opener, delays = FakeOpener([http_error(429, "120")]), []
        with self.assertRaises(ApiError):
            HttpTransport(opener=opener, sleep=delays.append).request("GET", BASE + "port/v1/accounts/me")
        self.assertEqual(delays, [])
        self.assertEqual(len(opener.calls), 1)

    def test_token_post_never_retries(self):
        opener, delays = FakeOpener([http_error(503)]), []
        with self.assertRaises(ApiError):
            HttpTransport(opener=opener, sleep=delays.append).request("POST", TOKEN, data=b"grant_type=refresh_token")
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(delays, [])

    def test_errors_do_not_leak_request_or_server_secrets(self):
        for exception in (http_error(400), URLError("sensitive-network-text")):
            opener = FakeOpener([exception])
            with self.subTest(exception=type(exception)), self.assertRaises(ApiError) as caught:
                HttpTransport(opener=opener).request("POST", TOKEN, data=b"secret-input")
            self.assertNotIn("sensitive", str(caught.exception))
            self.assertNotIn("secret", str(caught.exception))
            self.assertNotIn("logonvalidation", str(caught.exception))

    def test_invalid_json_and_oversize_rejected(self):
        for body in (b"not-json-sensitive", b"[]", b"null", b"{}     "):
            with self.subTest(body=body), self.assertRaises(ApiError):
                HttpTransport(opener=FakeOpener([body]), max_body=5).request("GET", BASE + "port/v1/accounts/me")


class ClientTests(unittest.TestCase):
    def test_401_refreshes_once(self):
        instance, transport, auth = client([ApiError("expired", status_code=401), {"Currency": "EUR"}])
        self.assertEqual(instance.balances(), {"Currency": "EUR"})
        self.assertEqual(auth.calls, [False, True])
        self.assertEqual(transport.calls[1][2]["headers"]["Authorization"], "Bearer fixture-renewed")

    def test_repeated_401_stops(self):
        instance, transport, auth = client([ApiError("expired", status_code=401), ApiError("expired", status_code=401)])
        with self.assertRaises(ApiError):
            instance.balances()
        self.assertEqual(auth.calls, [False, True])
        self.assertEqual(len(transport.calls), 2)

    def test_forbidden_url_never_obtains_token(self):
        instance, transport, auth = client([])
        with self.assertRaises(ReadOnlyViolation):
            instance._get(BASE + "trade/v2/orders")
        self.assertEqual(auth.calls, [])
        self.assertEqual(transport.calls, [])

    def test_paginated_accounts_preserve_count_parameter(self):
        instance, transport, _ = client([
            {"Data": [{"AccountKey": "one"}], "__next": "?%24skip=1&%24top=1"},
            {"Data": [{"AccountKey": "two"}], "__count": 2},
        ])
        self.assertEqual(instance.accounts(), [{"AccountKey": "one"}, {"AccountKey": "two"}])
        next_query = parse_qs(urlsplit(transport.calls[1][1]).query)
        self.assertEqual(next_query["$inlinecount"], ["AllPages"])

    def test_reported_count_continues_short_page(self):
        instance, transport, _ = client([
            {"Data": [{"PositionId": "one"}], "__count": 2},
            {"Data": [{"PositionId": "two"}], "__count": 2},
        ])
        self.assertEqual(len(instance.positions()), 2)
        self.assertEqual(parse_qs(urlsplit(transport.calls[1][1]).query)["$skip"], ["1"])

    def test_pagination_rejects_external_and_cross_endpoint_links(self):
        links = [
            "https://evil.invalid/?$skip=1", "//evil.invalid/?$skip=1",
            "https://gateway.saxobank.com/openapi/port/v1/accounts/me?$skip=1",
            BASE + "port/v1/positions/me?$skip=1",
            "../accounts/me?$skip=1", "?%24skip=1&%24skip=2",
            "?%24skip=1&Unknown=value",
            "?%24skip=1&%24inlinecount=NoPages",
        ]
        for link in links:
            instance, transport, auth = client([{"Data": [{}], "__next": link}])
            with self.subTest(link=link), self.assertRaises((ReadOnlyViolation, ApiError)):
                instance.accounts()
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(auth.calls, [False])

    def test_backwards_or_skipping_pages_fail_closed(self):
        for offset in (0, 2):
            instance, transport, _ = client([{"Data": [{}], "__next": f"?$skip={offset}&$top=100"}])
            with self.subTest(offset=offset), self.assertRaises(ApiError):
                instance.accounts()
            self.assertEqual(len(transport.calls), 1)

    def test_incomplete_and_malformed_collections_fail(self):
        for page in ({}, {"Data": ["wrong"]}, {"Data": [], "__count": 1},
                     {"Data": [], "__count": True}, {"Data": [], "__next": "?$skip=1"}):
            instance, _, _ = client([page])
            with self.subTest(page=page), self.assertRaises(ApiError):
                instance.accounts()

    def test_complete_snapshot_has_stable_scope(self):
        instance, transport, _ = client([
            {"ClientKey": "fixture-client"},
            {"Data": [{"ClientKey": "fixture-client", "Currency": "USD"}]},
            {"Currency": "EUR", "TotalValue": 123.5, "CashBalance": 10},
            {"Data": [{"PositionId": "one"}]}, {"Data": []},
            {"ClientKey": "fixture-client"},
        ])
        snapshot = instance.snapshot()
        self.assertEqual(snapshot["environment"], "SIM")
        self.assertEqual(snapshot["client_key"], "fixture-client")
        self.assertEqual(snapshot["currency"], "EUR")
        self.assertEqual(snapshot["total_value"], 123.5)
        self.assertTrue(snapshot["captured_at"].endswith("+00:00"))
        self.assertEqual(len(transport.calls), 6)

    def test_snapshot_rejects_missing_nonfinite_and_unreliable_balance(self):
        for balance in ({"Currency": "EUR"}, {"Currency": "EUR", "TotalValue": float("nan")},
                        {"Currency": "EUR", "TotalValue": True},
                        {"Currency": "EUR", "TotalValue": 1, "CalculationReliability": "Approximated"}):
            instance, _, _ = client([{"ClientKey": "fixture"}, {"Data": []}, balance])
            with self.subTest(balance=balance), self.assertRaises(ApiError):
                instance.snapshot()

    def test_snapshot_rejects_identity_change(self):
        instance, _, _ = client([
            {"ClientKey": "first"}, {"Data": []}, {"Currency": "EUR", "TotalValue": 1},
            {"Data": []}, {"Data": []}, {"ClientKey": "second"},
        ])
        with self.assertRaises(ApiError):
            instance.snapshot()


if __name__ == "__main__":
    unittest.main()
