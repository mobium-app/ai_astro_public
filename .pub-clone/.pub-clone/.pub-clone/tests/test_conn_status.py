"""Testy realnego statusu łączności przy zmianie trybów (sieć/tunel/remote_ai/opencode)."""

import unittest
from unittest import mock

from astro import config
from astro.core import conn_status as cs
from astro.remote_support import Provider


class NetworkTest(unittest.TestCase):
    def setUp(self):
        cs._NET_CACHE.update(ts=0.0, ok=False)

    def test_network_via_wifi(self):
        with mock.patch("astro.wifi.active_ssid", return_value="MojaSiec"):
            cs._NET_CACHE.update(ts=0.0, ok=False)
            self.assertTrue(cs.network_ok())

    def test_network_via_socket(self):
        with mock.patch("astro.wifi.active_ssid", return_value=""), \
             mock.patch("astro.wifi._has_default_route", return_value=False), \
             mock.patch("astro.core.conn_status.socket.create_connection") as conn:
            cs._NET_CACHE.update(ts=0.0, ok=False)
            self.assertTrue(cs.network_ok())
            self.assertTrue(conn.called)

    def test_network_down(self):
        with mock.patch("astro.wifi.active_ssid", return_value=""), \
             mock.patch("astro.wifi._has_default_route", return_value=False), \
             mock.patch("astro.core.conn_status.socket.create_connection",
                        side_effect=OSError("brak")):
            cs._NET_CACHE.update(ts=0.0, ok=False)
            self.assertFalse(cs.network_ok())


class PcTest(unittest.TestCase):
    def test_pc_ok(self):
        with mock.patch("astro.remote_support._pc_online", return_value=True):
            self.assertTrue(cs.pc_ok())
        with mock.patch("astro.remote_support._pc_online", return_value=False):
            self.assertFalse(cs.pc_ok())


class SkynetTest(unittest.TestCase):
    def test_skynet_ok(self):
        with mock.patch("astro.core.conn_status.socket.create_connection") as conn:
            self.assertTrue(cs.skynet_ok("127.0.0.1:2200"))
            self.assertTrue(conn.called)

    def test_skynet_down(self):
        with mock.patch("astro.core.conn_status.socket.create_connection",
                        side_effect=OSError("brak")):
            self.assertFalse(cs.skynet_ok())

    def test_snapshot_includes_skynet(self):
        with mock.patch.object(cs, "network_ok", return_value=True), \
             mock.patch.object(cs, "pc_ok", return_value=True), \
             mock.patch.object(cs, "remote_ok", return_value=False), \
             mock.patch.object(cs, "opencode_ok", return_value=True), \
             mock.patch.object(cs, "skynet_ok", return_value=True):
            snap = cs.snapshot()
        self.assertIn("skynet", snap)
        self.assertTrue(snap["skynet"])


def _prov(label="groq", url="https://api.groq.com/openai/v1"):
    return Provider(label, url, "model", "key")


class RemoteTest(unittest.TestCase):
    def test_disabled(self):
        with mock.patch.object(config, "REMOTE_ENABLED", False):
            self.assertFalse(cs.remote_ok())

    def test_no_keys(self):
        with mock.patch.object(config, "REMOTE_ENABLED", True), \
             mock.patch("astro.remote_support.provider_chain", return_value=[]):
            self.assertFalse(cs.remote_ok())

    def test_reachability(self):
        with mock.patch.object(config, "REMOTE_ENABLED", True), \
             mock.patch("astro.remote_support.provider_chain", return_value=[_prov()]), \
             mock.patch("astro.core.conn_status.network_ok", return_value=True), \
             mock.patch("astro.core.conn_status._host_ok", return_value=True):
            self.assertTrue(cs.remote_ok())

    def test_real_probe(self):
        with mock.patch.object(config, "REMOTE_ENABLED", True), \
             mock.patch("astro.remote_support.provider_chain", return_value=[_prov()]), \
             mock.patch("astro.core.conn_status.network_ok", return_value=True), \
             mock.patch("astro.core.conn_status._probe", return_value=True) as pr:
            self.assertTrue(cs.remote_ok(probe=True))
            self.assertTrue(pr.called)


class OpencodeTest(unittest.TestCase):
    def test_ok(self):
        prov = _prov("opencode", "https://opencode.ai/zen/go/v1")
        with mock.patch("astro.remote_support.opencode_chain", return_value=[prov]), \
             mock.patch("astro.core.conn_status.network_ok", return_value=True), \
             mock.patch("astro.core.conn_status._probe", return_value=True):
            self.assertTrue(cs.opencode_ok())

    def test_no_key(self):
        with mock.patch("astro.remote_support.opencode_chain", return_value=[]):
            self.assertFalse(cs.opencode_ok())


class ModeStatusTest(unittest.TestCase):
    def test_exact_ok_messages(self):
        with mock.patch("astro.core.conn_status.mode_ok", return_value=True):
            self.assertEqual(cs.mode_status("offline"), "Status support - gotowe.")
            self.assertEqual(cs.mode_status("komputer"), "Status komputer - gotowe.")
            self.assertEqual(cs.mode_status("premium"), "Status premium - gotowe.")

    def test_exact_error_messages(self):
        with mock.patch("astro.core.conn_status.mode_ok", return_value=False):
            self.assertEqual(
                cs.mode_status("offline"),
                "Status support - błąd: żaden dostawca (remote_ai) nie jest podłączony.")
            self.assertEqual(cs.mode_status("komputer"),
                             "Status komputer - błąd: komputer nie jest podłączony.")
            self.assertEqual(cs.mode_status("premium"),
                             "Status premium - błąd: opencode nie działa.")

    def test_mode_reply_offline_ok(self):
        with mock.patch("astro.core.conn_status.mode_ok", return_value=True), \
             mock.patch("astro.core.conn_status.network_ok", return_value=True):
            r = cs.mode_reply("offline")
        self.assertIn("Uruchamiam tryb offline", r)
        self.assertIn("Status support - gotowe", r)

    def test_mode_reply_premium_error_fallback(self):
        with mock.patch("astro.core.conn_status.mode_ok", return_value=False), \
             mock.patch("astro.core.conn_status.network_ok", return_value=True):
            r = cs.mode_reply("premium")
        self.assertIn("opencode nie działa", r)
        self.assertIn("Pracuję lokalnie", r)

    def test_mode_reply_no_network(self):
        with mock.patch("astro.core.conn_status.mode_ok", return_value=False), \
             mock.patch("astro.core.conn_status.network_ok", return_value=False):
            r = cs.mode_reply("komputer")
        self.assertIn("Brak sieci Wi-Fi", r)
        self.assertIn("komputer nie jest podłączony", r)


if __name__ == "__main__":
    unittest.main()
