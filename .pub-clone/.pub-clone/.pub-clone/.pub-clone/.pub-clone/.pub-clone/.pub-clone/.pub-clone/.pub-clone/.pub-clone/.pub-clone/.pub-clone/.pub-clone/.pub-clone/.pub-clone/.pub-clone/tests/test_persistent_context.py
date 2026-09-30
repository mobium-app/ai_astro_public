"""Testy kontekstu trwałego (P4): digesty dzienne, archiwum .md, stały blok startowy."""

import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta

from astro import config
from astro.core import persistent_context as pc
from astro.memory import Memory


def _ts_at(day, hour=12):
    d = datetime.strptime(day, "%Y-%m-%d") + timedelta(hours=hour)
    return d.timestamp()


class PersistentContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mem = Memory(os.path.join(self.tmp, "mem.db"))
        self.addCleanup(self.mem.con.close)
        self.today = pc.day_key()
        self.yesterday = (datetime.strptime(self.today, "%Y-%m-%d")
                          - timedelta(days=1)).strftime("%Y-%m-%d")

    def _add(self, day, user, assistant="ok"):
        self.mem.add_session_turn(user, assistant, ts=_ts_at(day))

    def test_summarize_dedupes_and_caps(self):
        turns = [{"user": "co to jest fotosynteza"}, {"user": "Co to jest fotosynteza"},
                 {"user": "która godzina"}]
        out = pc.summarize_turns(turns)
        self.assertEqual(out.count("fotosynteza"), 1)
        self.assertIn("która godzina", out)

    def test_refresh_stores_digest_for_past_day(self):
        self._add(self.yesterday, "pokaż zasoby")
        self._add(self.yesterday, "która godzina")
        saved = pc.refresh(self.mem, days=7)
        self.assertGreaterEqual(saved, 1)
        digest = self.mem.context_digest(self.yesterday)
        self.assertIsNotNone(digest)
        self.assertIn("pokaż zasoby", digest["summary"])
        self.assertEqual(digest["turns"], 2)

    def test_build_block_includes_day_and_summary(self):
        self.mem.set_session_summary("tryb komputer; podaj ip", last_ts=time.time())
        self._add(self.yesterday, "pokaż zasoby zdalne")
        block = pc.build_block(self.mem, days=7)
        self.assertIn(self.yesterday, block)
        self.assertIn("pokaż zasoby zdalne", block)
        self.assertIn("Ostatni wątek rozmowy", block)

    def test_build_block_respects_budget(self):
        for i in range(0, 40):
            self._add(self.yesterday, f"pytanie numer {i} o bardzo dlugi temat {i}")
        block = pc.build_block(self.mem, days=7, max_chars=120)
        self.assertLessEqual(len(block), 120)

    def test_build_block_empty_without_data(self):
        self.assertEqual(pc.build_block(self.mem), "")

    def test_export_day_writes_markdown(self):
        self._add(self.yesterday, "pokaż temperaturę", "Temperatura wynosi 45 stopni.")
        out = os.path.join(self.tmp, "ctx")
        path = pc.export_day(self.mem, self.yesterday, out_dir=out)
        self.assertTrue(path and os.path.isfile(path))
        text = open(path, encoding="utf-8").read()
        self.assertIn("pokaż temperaturę", text)
        self.assertIn("Temperatura wynosi 45 stopni.", text)

    def test_warm_start(self):
        self._add(self.yesterday, "co słychać")
        res = pc.warm_start(self.mem)
        self.assertGreaterEqual(res.get("digests", 0), 1)
        self.assertGreaterEqual(res.get("files", 0), 1)


class BuildContextPinnedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mem = Memory(os.path.join(self.tmp, "mem.db"))
        self.addCleanup(self.mem.con.close)

    def test_pinned_after_system_prompt(self):
        from astro.core.context import SYSTEM_PROMPT, build_context
        msgs = build_context("cześć", self.mem, pinned="KONTEKST-START")
        self.assertEqual(msgs[0]["content"], SYSTEM_PROMPT)
        self.assertEqual(msgs[1]["content"], "KONTEKST-START")

    def test_no_pinned_by_default(self):
        from astro.core.context import build_context
        msgs = build_context("cześć", self.mem)
        self.assertNotIn("KONTEKST-START", [m.get("content") for m in msgs])


if __name__ == "__main__":
    unittest.main()
