"""Testy stanu afektywnego ASTRO (E7.2): PAD, zanik, magazyn, komendy, kontekst."""

import sys
import types
import unittest

from astro.affect import AffectState, AffectStore
from astro.affect.affect import ANCHORS
from astro.core import affect_flow
from astro.memory import Memory


class TestState(unittest.TestCase):
    def test_apply_effective(self):
        s = AffectState()
        s.apply(0.5, 0.2, 0.1)
        eff = s.effective()
        self.assertAlmostEqual(eff[0], 0.625)
        self.assertAlmostEqual(s.mood[0], 0.125)

    def test_clamp(self):
        s = AffectState()
        s.apply(5.0, -5.0, 0.0)
        self.assertEqual(s.emotion[0], 1.0)
        self.assertEqual(s.emotion[1], -1.0)

    def test_decay_half_life(self):
        s = AffectState(emotion=(1.0, 0.0, 0.0), ts=1000.0, emotion_half_life=100.0)
        s.decay(now=1100.0)
        self.assertAlmostEqual(s.emotion[0], 0.5, places=4)

    def test_describe_joy(self):
        s = AffectState()
        s.apply(0.7, 0.6, 0.3)
        label, guidance = s.describe(now=s.ts)
        self.assertEqual(label, "radosna")
        self.assertTrue(guidance)

    def test_context_block(self):
        s = AffectState()
        block = s.context_block(now=s.ts)
        self.assertIn("NASTRÓJ ASTRO", block)
        self.assertEqual(block, s.context_block(now=s.ts))

    def test_anchors_complete(self):
        for label, guidance, pad in ANCHORS:
            self.assertTrue(label and guidance and len(pad) == 3)


class TestStore(unittest.TestCase):
    def test_roundtrip(self):
        mem = Memory(":memory:")
        st = mem.affect
        s = AffectState()
        s.apply(0.4, 0.2, 0.0)
        st.save(s)
        loaded = st.load()
        self.assertAlmostEqual(loaded.effective()[0], 0.5, places=3)

    def test_decay_across_load(self):
        mem = Memory(":memory:")
        st = mem.affect
        s = AffectState(emotion=(1.0, 0.0, 0.0))
        st.save(s)
        st.con.execute("UPDATE affect SET ts=? WHERE user_id='default'", (s.ts - 180,))
        st.con.commit()
        self.assertLess(st.load().effective()[0], 0.6)

    def test_reset(self):
        mem = Memory(":memory:")
        st = mem.affect
        st.save(AffectState())
        st.reset()
        self.assertEqual(st.load().effective(), (0.0, 0.0, 0.0))


class TestFlow(unittest.TestCase):
    def test_mood_query(self):
        mem = Memory(":memory:")
        agent = types.SimpleNamespace(ctx=types.SimpleNamespace(memory=mem))
        reply, route = affect_flow.handle("jaki masz nastrój", agent)
        self.assertEqual(route, "affect")
        self.assertIn("nastrój", reply.lower())

    def test_none_without_memory(self):
        agent = types.SimpleNamespace(ctx=types.SimpleNamespace())
        self.assertIsNone(affect_flow.handle("jaki masz nastrój", agent))

    def test_dispatch_routes(self):
        import astro.core.dispatch  # noqa: F401
        d = sys.modules["astro.core.dispatch"]
        mem = Memory(":memory:")
        agent = types.SimpleNamespace(ctx=types.SimpleNamespace(memory=mem), memory=mem)
        res = d.dispatch("jaki masz nastrój", agent)
        self.assertEqual(res.route, "affect")


class TestContext(unittest.TestCase):
    def test_build_context_includes_mood(self):
        from astro.core.context import build_context
        mem = Memory(":memory:")
        msgs = build_context("cześć", mem)
        system_text = " ".join(m["content"] for m in msgs if m["role"] == "system")
        self.assertIn("NASTRÓJ ASTRO", system_text)


if __name__ == "__main__":
    unittest.main()
