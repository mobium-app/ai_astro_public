"""Testy logowania ASTRO (C6): logger + zapis do pliku."""

import logging
import os
import unittest

from astro import config, log


class TestLogging(unittest.TestCase):
    def test_logger_and_file(self):
        lg = log.get_logger("test")
        self.assertTrue(lg.name.startswith("astro"))
        lg.info("astro-test-log-line")
        for h in logging.getLogger("astro").handlers:
            try:
                h.flush()
            except Exception:
                pass
        path = os.path.join(str(config.LOGS_DIR), "astro.log")
        self.assertTrue(os.path.exists(path))
        # Czytamy tylko ogon (log bywa duży / rotowany) — wystarczy potwierdzić zapis.
        with open(path, encoding="utf-8", errors="replace") as fh:
            try:
                fh.seek(0, os.SEEK_END)
                fh.seek(max(0, fh.tell() - 65536))
            except OSError:
                pass
            self.assertIn("astro-test-log-line", fh.read())


if __name__ == "__main__":
    unittest.main()
