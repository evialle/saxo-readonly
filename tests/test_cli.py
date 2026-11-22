import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from saxo_readonly.cli import main
from saxo_readonly.errors import SaxoError
from saxo_readonly.history import SnapshotStore
from test_history_alerts import sample


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cfg = SimpleNamespace(env="SIM", history_file=Path(self.temp.name) / "history.sqlite3")
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        for ctx in (patch("saxo_readonly.cli.Config.load", return_value=self.cfg),
                    contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr)):
            ctx.__enter__()
            self.addCleanup(ctx.__exit__, None, None, None)

    def test_offline_commands_do_not_construct_auth(self):
        with patch("saxo_readonly.cli.AuthManager", side_effect=AssertionError("network auth")):
            for command in ("history", "alerts", "report"):
                self.assertEqual(0, main([command]))

    def test_alert_exit_status(self):
        store = SnapshotStore(self.cfg.history_file)
        store.save(sample())
        store.save(sample(110))
        self.assertEqual(3, main(["alerts", "--fail-on-alert"]))
        self.assertEqual(0, main(["alerts"]))

    def test_incomplete_fetch_does_not_commit(self):
        with patch("saxo_readonly.cli.SaxoClient") as client:
            client.return_value.snapshot.side_effect = SaxoError("Incomplete response")
            self.assertEqual(1, main(["snapshot"]))
        self.assertFalse(self.cfg.history_file.exists())
        self.assertIn("Incomplete response", self.stderr.getvalue())

    def test_callback_requires_interactive_terminal(self):
        with patch("sys.stdin.isatty", return_value=False):
            self.assertEqual(1, main(["auth-finish"]))

    def test_invalid_interval_makes_no_request(self):
        with patch("saxo_readonly.cli.AuthManager") as auth:
            self.assertEqual(1, main(["refresh", "--interval", "nan"]))
            auth.return_value.refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
