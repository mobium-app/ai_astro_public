"""C7: jedno źródło prawdy dla czasowników komend (`safety/verbs.py`)."""

import unittest

from astro.safety import intent, normalize, verbs


class TestVerbsSingleSource(unittest.TestCase):
    def test_intent_uses_shared_set(self):
        self.assertIs(intent.EXEC_VERBS, verbs.EXEC_FIRST)

    def test_normalize_regexes_built_from_verbs(self):
        self.assertEqual(normalize.CLS_IMPERATIVE.pattern, verbs.imperative_re().pattern)
        self.assertEqual(normalize.CLS_POLITE_CMD.pattern, verbs.polite_cmd_re().pattern)

    def test_representative_behaviour(self):
        self.assertEqual(intent.classify_intent("uruchom przeglądarkę"), "command")
        self.assertEqual(intent.classify_intent("co to jest linux"), "question")
        self.assertTrue(normalize.CLS_IMPERATIVE.search("a teraz zaktualizuj pakiety"))
        # Regexe działają na tekście znormalizowanym (bez diakrytyków) — jak w runtime.
        self.assertTrue(normalize.CLS_POLITE_CMD.search(
            normalize.normalize_facts("czy możesz uruchomić aktualizację")))
        self.assertTrue(verbs.mutate_re().search("zaktualizuj aplikacje systemowe"))
        self.assertTrue(verbs.run_goal_re().search("uruchom serwer www"))
        self.assertTrue(verbs.setup_goal_re().search("skonfiguruj firewall"))


if __name__ == "__main__":
    unittest.main()
