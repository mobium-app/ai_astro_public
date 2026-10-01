"""Testy setup/pairing — autoimport konfiguracji i głosu dla kreatora apki."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from astro.mobility import setup


class TestSetup(unittest.TestCase):
    def test_pairing_key_generacja_i_odczyt(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(setup, "PAIRING_PATH", Path(tmp) / "pairing.key"):
                key = setup.pairing_key(regenerate=True)
                self.assertEqual(len(key), 6)
                self.assertTrue(key.isalnum())
                again = setup.pairing_key()
                self.assertEqual(key, again)
                mode = (Path(tmp) / "pairing.key").stat().st_mode & 0o777
                self.assertEqual(mode, 0o600)

    def test_setup_payload_zawiera_sekret_i_topik(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secrets = root / "secrets"
            secrets.mkdir()
            (secrets / "mobility.secret").write_text("tajne123")
            (secrets / "ntfy_topic").write_text("astro-mob-test")
            with mock.patch.object(setup, "ROOT", root):
                payload = setup.setup_payload()
                self.assertEqual(payload["token_secret"], "tajne123")
                self.assertEqual(payload["ntfy_topic"], "astro-mob-test")
                self.assertEqual(payload["name"], "s5-astro")
                self.assertIn("voice_size", payload)


if __name__ == "__main__":
    unittest.main()