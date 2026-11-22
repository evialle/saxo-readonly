import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from saxo_readonly.config import Config, default_root
from saxo_readonly.errors import ConfigError


class ConfigTests(unittest.TestCase):
    def test_environment_endpoints_and_storage_are_separate(self):
        sim, live = Config(), Config(env="live")
        self.assertEqual(sim.api_base, "https://gateway.saxobank.com/sim/openapi/")
        self.assertEqual(live.auth_base, "https://live.logonvalidation.net")
        self.assertNotEqual(sim.data_dir, live.data_dir)
        self.assertNotEqual(sim.binding, live.binding)
        self.assertEqual(sim.data_dir.parent, default_root())

    def test_rejects_unsafe_redirects(self):
        for uri in ("http://evil.example/callback", "https://user:secret@example.com/callback",
                    "https://example.com/callback#fragment", "https://example.com/callback?a=b",
                    "http://localhost:wrong/callback", "\thttps://example.com/callback"):
            with self.subTest(uri=uri), self.assertRaises(ConfigError):
                Config(redirect_uri=uri)

    def test_repr_hides_app_credentials(self):
        cfg = Config(app_key="sensitive-key", app_secret="sensitive-secret")
        self.assertNotIn("sensitive", repr(cfg))

    def test_offline_configuration_needs_no_credentials(self):
        cfg = Config()
        with self.assertRaises(ConfigError):
            cfg.require_auth()
        with self.assertRaises(ConfigError):
            Config(app_key="test-key", flow="code").require_auth()

    def test_env_overrides_file_and_explicit_path_wins(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.env"
            path.write_text("SAXO_APP_KEY='from-file'\nSAXO_ENV=SIM\n", encoding="utf-8")
            path.chmod(0o600)
            with patch.dict(os.environ, {"SAXO_CONFIG_FILE": "missing-config.env", "SAXO_ENV": "LIVE", "SAXO_DATA_DIR": temporary}, clear=True):
                cfg = Config.load(path)
            self.assertEqual(cfg.app_key, "from-file")
            self.assertEqual(cfg.env, "LIVE")

    def test_missing_explicit_config_errors_without_echoing_path(self):
        with self.assertRaises(ConfigError) as caught:
            Config.load(Path("missing-secret-file.env"))
        self.assertNotIn("missing-secret", str(caught.exception))

    def test_binding_changes_with_app_redirect_and_flow(self):
        cfg = Config(app_key="first")
        self.assertNotEqual(cfg.binding, Config(app_key="second").binding)
        self.assertNotEqual(cfg.binding, Config(app_key="first", flow="code").binding)
        self.assertNotEqual(cfg.binding, Config(app_key="first", redirect_uri="https://example.com").binding)

    @unittest.skipIf(os.name == "nt", "POSIX permission semantics")
    def test_insecure_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.env"
            path.write_text("SAXO_APP_KEY=example", encoding="utf-8")
            path.chmod(0o644)
            with self.assertRaises(ConfigError):
                Config.load(path)
