import copy
import contextlib
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from saxo_readonly.alerts import analyze, render_report
from saxo_readonly.errors import SaxoError
from saxo_readonly.history import SnapshotStore


def sample(total=100, **changes):
    result = {
        "environment": "SIM", "client_key": "synthetic-client", "currency": "EUR",
        "captured_at": "2026-11-22T12:00:00+00:00", "total_value": total,
        "accounts": [{"AccountKey": "synthetic-account"}], "balances": {"TotalValue": total},
        "positions": [], "netpositions": [],
    }
    result.update(changes)
    return result


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "private" / "history.sqlite3"
        self.store = SnapshotStore(self.path)

    def test_empty_read_does_not_create_files(self):
        self.assertEqual([], self.store.recent("SIM"))
        self.assertFalse(self.path.exists())

    def test_roundtrip_and_environment_isolation(self):
        first = self.store.save(sample())
        self.store.save(sample(200, environment="LIVE"))
        last = self.store.save(sample(110))
        self.assertEqual([last, first], self.store.recent("SIM"))
        self.assertEqual(200, self.store.recent("LIVE")[0]["total_value"])
        self.assertEqual([last], self.store.recent("SIM", 1))

    def test_failed_snapshot_preserves_history(self):
        self.store.save(sample())
        for changes in ({"total_value": math.nan}, {"total_value": True},
                        {"client_key": ""}, {"accounts": [{}]},
                        {"captured_at": "2026-01-01"}, {"positions": ["bad"]},
                        {"balances": {"a": math.inf}}):
            with self.subTest(changes=changes), self.assertRaises(SaxoError):
                self.store.save(sample(**changes))
        self.assertEqual(1, len(self.store.recent("SIM")))

    def test_newer_and_legacy_schema_refused(self):
        self.store.save(sample())
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA user_version=2")
        with self.assertRaises(SaxoError):
            self.store.recent("SIM")
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA user_version=0")
        with self.assertRaises(SaxoError):
            self.store.save(sample())

    def test_invalid_limit(self):
        for limit in (-1, 0, 1001):
            with self.assertRaises(SaxoError):
                self.store.recent("SIM", limit)


class AlertTests(unittest.TestCase):
    def test_threshold_boundary_and_drop(self):
        for value in (97, 103):
            result = analyze([sample(value), sample()], 3)
            self.assertTrue(result["triggered"])
            self.assertEqual(abs(result["comparison"]["change_pct"]), 3)
        self.assertFalse(analyze([sample(102), sample()], 3)["triggered"])

    def test_negative_and_zero_baseline(self):
        self.assertEqual(10, analyze([sample(-90), sample(-100)])["comparison"]["change_pct"])
        zero = analyze([sample(10), sample(0)])
        self.assertEqual("zero_baseline", zero["reason"])
        self.assertIsNone(zero["comparison"]["change_pct"])

    def test_different_scopes_never_compared(self):
        for changes in ({"currency": "USD"}, {"client_key": "other"},
                        {"environment": "LIVE"}, {"accounts": [{"AccountKey": "other"}]}):
            with self.subTest(changes=changes):
                result = analyze([sample(200, **changes), sample()])
                self.assertFalse(result["triggered"])
                self.assertIsNone(result["comparison"])

    def test_order_of_accounts_does_not_change_scope(self):
        previous = sample(accounts=[{"AccountKey": "a"}, {"AccountKey": "b"}])
        current = copy.deepcopy(previous)
        current["accounts"].reverse()
        self.assertEqual("comparable", analyze([current, previous])["reason"])

    def test_instrument_alert_without_baseline(self):
        item = {"NetPositionId": "SYNTHETIC", "NetPositionView": {
            "InstrumentPriceDayPercentChange": -4, "CurrentPriceDelayMinutes": 15}}
        result = analyze([sample(netpositions=[item])])
        self.assertTrue(result["triggered"])
        self.assertEqual(15, result["alerts"][0]["price_delay_minutes"])

    def test_empty_report_and_invalid_threshold(self):
        self.assertIn("No snapshots", render_report([]))
        self.assertIn("no_previous_snapshot", render_report([sample()]))
        for threshold in (0, -1, math.nan, math.inf):
            with self.assertRaises(SaxoError):
                analyze([], threshold)


if __name__ == "__main__":
    unittest.main()
