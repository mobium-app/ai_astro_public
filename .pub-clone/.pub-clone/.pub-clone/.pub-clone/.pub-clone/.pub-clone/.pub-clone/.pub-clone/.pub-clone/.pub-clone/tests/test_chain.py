"""Testy logiki łańcuchów narzędzi (E6): kiedy ponaglać i o jakie narzędzie."""

import unittest

from astro.core.agent import _needs_chain, chain_nudge_message, chain_tools


class TestChainTools(unittest.TestCase):
    def test_two_tools(self):
        tools = chain_tools("Sprawdź temperaturę procesora i wyszukaj w internecie")
        self.assertIn("system_info", tools)
        self.assertIn("web_search", tools)

    def test_read_and_web(self):
        tools = chain_tools("Przeczytaj /etc/os-release i wyszukaj informacje")
        self.assertIn("read_file", tools)
        self.assertIn("web_search", tools)

    def test_npu_and_system(self):
        tools = chain_tools("Sprawdź stan NPU oraz temperaturę procesora")
        self.assertEqual(set(tools), {"npu_status", "system_info"})


class TestNeedsChain(unittest.TestCase):
    def test_zero_tools_executable_nudges(self):
        self.assertTrue(_needs_chain("Sprawdź stan NPU oraz temperaturę procesora", []))

    def test_zero_tools_question_no_nudge(self):
        self.assertFalse(_needs_chain("Opowiedz o internecie i systemie", []))

    def test_one_tool_missing_second(self):
        self.assertTrue(_needs_chain("Sprawdź temperaturę i wyszukaj w internecie",
                                     ["system_info"]))

    def test_complete_no_nudge(self):
        self.assertFalse(_needs_chain("Sprawdź stan NPU oraz temperaturę procesora",
                                      ["npu_status", "system_info"]))

    def test_simple_command_no_nudge(self):
        self.assertFalse(_needs_chain("Sprawdź temperaturę procesora", []))

    def test_no_conjunction_no_nudge(self):
        self.assertFalse(_needs_chain("Sprawdź stan NPU", []))


class TestNudgeMessage(unittest.TestCase):
    def test_zero_tools_lists_all(self):
        msg = chain_nudge_message("Sprawdź temperaturę procesora i wyszukaj w internecie", [])
        self.assertIn("system_info", msg)
        self.assertIn("web_search", msg)

    def test_one_tool_mentions_remaining(self):
        msg = chain_nudge_message("Sprawdź temperaturę procesora i wyszukaj w internecie",
                                  ["system_info"])
        self.assertIn("web_search", msg)
        self.assertNotIn("system_info", msg.split("narzędzie")[-1])


if __name__ == "__main__":
    unittest.main()
