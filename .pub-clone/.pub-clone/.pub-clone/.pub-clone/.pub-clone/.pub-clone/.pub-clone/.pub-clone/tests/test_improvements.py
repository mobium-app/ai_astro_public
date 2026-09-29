"""Testy ulepszeń: selektor narzędzi, silniki audio, barge-in, MCP, Home Assistant, wizja, polityka."""

import json
import os
import sys
import tempfile
import textwrap
import threading
import time
import types
import unittest
from unittest import mock

from astro import backends as B
from astro import config
from astro.audio import engines
from astro.audio.tts import TTS
from astro.safety import Confirmer
from astro.scripts.e6_gate import HOLDOUT_TESTS
from astro.tools import ToolContext, registry
from astro.tools import home as home_tools
from astro.tools import mcp as mcp_tools
from astro.tools import vision as vision_tools
from astro.mcp_client import StdioMCPClient


class TestSelectorRecall(unittest.TestCase):
    def test_holdout_tools_are_candidates(self):
        for q, expect, _ in HOLDOUT_TESTS:
            picked = registry.select_names(q, config.MAX_TOOLS)
            self.assertTrue(any(e in picked for e in expect),
                            f"brak {expect} dla: {q} -> {picked}")


class TestEngines(unittest.TestCase):
    def test_builtin_and_custom(self):
        self.assertIn("piper", engines.tts_engines())
        self.assertIn("npu", engines.stt_engines())

        engines.register_tts("fake", lambda **kw: "TTS-FAKE")
        engines.register_stt("fake", lambda **kw: "STT-FAKE")
        self.assertEqual(engines.build_tts("fake"), "TTS-FAKE")
        self.assertEqual(engines.build_stt("fake"), "STT-FAKE")
        with self.assertRaises(KeyError):
            engines.build_tts("nie-ma-takiego")


class TestBargeStop(unittest.TestCase):
    def test_stop_terminates_playback(self):
        wav = os.path.join(tempfile.mkdtemp(), "x.wav")
        open(wav, "wb").close()
        tts = TTS(engine="none")
        tts.play_cmd = lambda w: ["sleep", "30"]
        holder = {}
        th = threading.Thread(target=lambda: holder.update(ok=tts.play(wav)))
        th.start()
        time.sleep(0.4)
        self.assertTrue(tts.stop())
        th.join(timeout=5)
        self.assertFalse(th.is_alive())
        self.assertFalse(holder.get("ok"))


class TestPolicySpec(unittest.TestCase):
    def test_model_mode_and_table(self):
        self.assertEqual(B.model_for("tools"), config.MODEL_TOOLS)
        self.assertEqual(B.mode_for("tools"), config.MODE_TOOLS)
        table = B.policy_table()
        self.assertIn("tools", table)
        self.assertIn("model", table["tools"])
        self.assertIn("mode", table["tools"])
        self.assertTrue(table["tools"]["order"])


class TestMCPServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = os.path.join(tempfile.mkdtemp(), "mock_mcp.py")
        with open(cls.server, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent('''
                import sys, json
                def send(o):
                    sys.stdout.write(json.dumps(o) + "\\n"); sys.stdout.flush()
                for line in sys.stdin:
                    line = line.strip()
                    if not line:
                        continue
                    msg = json.loads(line)
                    method, rid = msg.get("method"), msg.get("id")
                    if method == "initialize":
                        send({"jsonrpc": "2.0", "id": rid, "result": {
                            "protocolVersion": "2024-11-05", "capabilities": {},
                            "serverInfo": {"name": "mock", "version": "1"}}})
                    elif method == "tools/list":
                        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [{
                            "name": "echo", "description": "Echo",
                            "inputSchema": {"type": "object",
                                            "properties": {"text": {"type": "string"}},
                                            "required": ["text"]}}]}})
                    elif method == "tools/call":
                        args = (msg.get("params") or {}).get("arguments") or {}
                        send({"jsonrpc": "2.0", "id": rid, "result": {
                            "content": [{"type": "text", "text": "echo:" + str(args.get("text"))}]}})
                    elif method == "notifications/initialized":
                        pass
            '''))

    def test_client_and_registration(self):
        client = StdioMCPClient(sys.executable, [self.server], timeout=10)
        self.addCleanup(client.close)
        client.initialize()
        tools = client.list_tools()
        self.assertEqual(tools[0]["name"], "echo")
        result = client.call_tool("echo", {"text": "hej"})
        self.assertEqual(result["content"][0]["text"], "echo:hej")

        reg = type(registry)()
        cfg = os.path.join(tempfile.mkdtemp(), "mcp.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({"servers": [{"name": "mock", "command": sys.executable,
                                    "args": [self.server], "read_only": True}]}, fh)
        names = mcp_tools.register_mcp_tools(reg, path=cfg)
        self.assertEqual(names, ["mcp_mock_echo"])
        ctx = ToolContext(settings=config, memory=None,
                          confirmer=Confirmer(auto=True))
        res = reg.execute("mcp_mock_echo", {"text": "abc"}, ctx)
        self.assertTrue(res.ok)
        self.assertIn("echo:abc", res.text)
        mcp_tools.close_all()

    def test_gated_when_not_read_only(self):
        reg = type(registry)()
        cfg = os.path.join(tempfile.mkdtemp(), "mcp.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({"servers": [{"name": "mock", "command": sys.executable,
                                    "args": [self.server], "read_only": False}]}, fh)
        names = mcp_tools.register_mcp_tools(reg, path=cfg)
        self.assertEqual(names, ["mcp_mock_echo"])
        ctx = ToolContext(settings=config, memory=None,
                          confirmer=Confirmer(auto=False))
        res = reg.execute("mcp_mock_echo", {"text": "abc"}, ctx)
        self.assertFalse(res.ok)
        self.assertTrue(res.data and res.data.get("pending"))
        mcp_tools.close_all()


class TestHomeAssistant(unittest.TestCase):
    def _cfg(self):
        return {"ha_url": "http://ha.local:8123", "token": "t",
                "entities": {"salon": "light.salon"}}

    def test_status_and_command(self):
        with mock.patch.object(home_tools, "load_ha", return_value=self._cfg()), \
             mock.patch.object(home_tools, "_ha_api",
                               return_value={"state": "on"}) as api:
            ctx = ToolContext(settings=config, memory=None,
                              confirmer=Confirmer(auto=True))
            res = registry.execute("home_status", {"entity": "salon"}, ctx)
            self.assertTrue(res.ok)
            self.assertIn("on", res.text)
            res2 = registry.execute("home_command",
                                               {"entity": "salon", "action": "on"}, ctx)
            self.assertTrue(res2.ok)
            self.assertTrue(api.called)

    def test_entity_outside_whitelist(self):
        with mock.patch.object(home_tools, "load_ha", return_value=self._cfg()):
            ctx = ToolContext(settings=config, memory=None,
                              confirmer=Confirmer(auto=True))
            res = registry.execute("home_command",
                                              {"entity": "drzwi", "action": "on"}, ctx)
            self.assertFalse(res.ok)

    def test_unconfigured(self):
        with mock.patch.object(home_tools, "load_ha", return_value=None):
            ctx = ToolContext(settings=config)
            res = registry.execute("home_status", {}, ctx)
            self.assertFalse(res.ok)


class TestVision(unittest.TestCase):
    def test_no_camera_graceful(self):
        ctx = ToolContext(settings=config)
        with mock.patch.object(vision_tools, "camera_present", return_value=False):
            res = registry.execute("camera_look", {"question": "co?"}, ctx)
        self.assertFalse(res.ok)
        self.assertIn("Brak kamery", res.text)

    def test_camera_but_no_vlm(self):
        ctx = ToolContext(settings=config)
        with mock.patch.object(vision_tools, "camera_present", return_value=True), \
             mock.patch.object(vision_tools, "network_camera_enabled", return_value=False), \
             mock.patch.object(vision_tools, "capture_frame", return_value="/tmp/f.jpg"), \
             mock.patch.object(vision_tools, "vlm_ready", return_value=False):
            res = registry.execute("camera_look", {"question": "co?"}, ctx)
        self.assertTrue(res.ok)
        self.assertIn("klatk", res.text.lower())


if __name__ == "__main__":
    unittest.main()
