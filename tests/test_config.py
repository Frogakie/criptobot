import json
import os
import tempfile
import unittest
from pathlib import Path

from criptobot.config import Config


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.json"
        self._write({"symbol": "BTCUSDT", "poll_seconds": 30})

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, data_or_text, bump=0):
        text = data_or_text if isinstance(data_or_text, str) else json.dumps(data_or_text)
        self.path.write_text(text, encoding="utf-8")
        if bump:
            st = self.path.stat()
            os.utime(self.path, (st.st_atime, st.st_mtime + bump))

    def test_initial_load(self):
        cfg = Config(self.path)
        self.assertEqual(cfg.get("symbol"), "BTCUSDT")
        self.assertEqual(cfg.get("missing", 42), 42)

    def test_no_reload_if_unchanged(self):
        cfg = Config(self.path)
        self.assertFalse(cfg.reload())

    def test_hot_reload_on_change(self):
        cfg = Config(self.path)
        self._write({"symbol": "ETHUSDT", "poll_seconds": 30}, bump=5)
        self.assertTrue(cfg.reload())
        self.assertEqual(cfg.get("symbol"), "ETHUSDT")

    def test_invalid_json_keeps_previous(self):
        cfg = Config(self.path)
        self._write("{ esto no es json", bump=5)
        self.assertFalse(cfg.reload())
        self.assertEqual(cfg.get("symbol"), "BTCUSDT")

    def test_missing_file_on_start_exits(self):
        with self.assertRaises(SystemExit):
            Config(Path(self.tmp.name) / "no_existe.json")


if __name__ == "__main__":
    unittest.main()
