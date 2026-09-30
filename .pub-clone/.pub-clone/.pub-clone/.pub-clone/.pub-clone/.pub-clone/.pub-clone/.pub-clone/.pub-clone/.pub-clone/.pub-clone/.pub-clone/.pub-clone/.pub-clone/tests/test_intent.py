"""Testy SWITCH-a intencji: komenda wykonywalna vs pytanie/teoria (decyzja 2026-09-20)."""

import unittest

from astro import safety
from astro.safety import classify_intent, is_executable_command


class TestExecutableCommands(unittest.TestCase):
    def test_leading_exec_verbs(self):
        for text in ("uruchom aktualizację repozytoriów",
                     "włącz usługę ssh",
                     "wyłącz wifi",
                     "pokaż temperaturę procesora",
                     "wyświetl wolne miejsce na dysku",
                     "oblicz 12 * 8",
                     "formatuj dysk zewnętrzny",
                     "kopiuj plik do backupu",
                     "przenieś raport do archiwum",
                     "resetuj konfigurację sieci",
                     "znajdź duże pliki w /var/log",
                     "wyszukaj sterowniki do karty",
                     "raportuj stan systemu",
                     "sprawdź temperaturę procesora i wolne miejsce na dysku",
                     "zainstaluj pakiet htop",
                     "zapisz notatkę o kawie"):
            self.assertEqual(classify_intent(text), "command", text)
            self.assertTrue(is_executable_command(text), text)

    def test_command_with_domain_word_not_theory(self):
        for text in ("uruchom aktualizację systemu",
                     "pokaż analizę zużycia dysku",
                     "wygeneruj raport z błędów"):
            self.assertEqual(classify_intent(text), "command", text)


class TestQuestionsAndTheory(unittest.TestCase):
    def test_leading_question_words(self):
        for text in ("co to jest Linux",
                     "czym jest inflacja?",
                     "dlaczego niebo jest niebieskie",
                     "czemu pada deszcz",
                     "jaki jest największy ssak",
                     "jaka jest różnica między TCP a UDP",
                     "jak działa DNS",
                     "gdzie leży Poznań",
                     "kiedy wybuchła II wojna światowa",
                     "ile kosztuje bilet"):
            self.assertEqual(classify_intent(text), "question", text)
            self.assertFalse(is_executable_command(text), text)

    def test_theory_phrases(self):
        for text in ("powiedz co to jest fotosynteza",
                     "powiedz mi co to grawitacja",
                     "z jakiego powodu nie działa prąd",
                     "dokonaj analizy tego zjawiska",
                     "wyjaśnij mi działanie DNS",
                     "wytłumacz krok po kroku jak działa silnik"):
            self.assertEqual(classify_intent(text), "question", text)
            self.assertFalse(is_executable_command(text), text)

    def test_theory_inside_command_is_question(self):
        self.assertEqual(classify_intent("pokaż mi jak działa DNS"), "question")
        self.assertEqual(classify_intent("wyświetl co to jest pamięć RAM"), "question")


class TestContextSwitch(unittest.TestCase):
    def test_short_followup_inherits_command(self):
        history = [{"text": "sprawdź temperaturę procesora", "label": "command"}]
        self.assertEqual(classify_intent("a teraz też na dysku", history=history), "command")

    def test_question_is_not_overridden_by_context(self):
        history = [{"text": "sprawdź temperaturę", "label": "command"}]
        self.assertEqual(classify_intent("jaka jest pogoda", history=history), "question")

    def test_history_accepts_raw_text(self):
        history = ["uruchom aktualizację repozytoriów"]
        self.assertEqual(classify_intent("teraz to samo na dysku", history=history), "command")


class TestSafetyIntegration(unittest.TestCase):
    def test_classify_request_matches_switch(self):
        self.assertEqual(safety.classify_request("uruchom usługę ssh"), "command")
        self.assertEqual(safety.classify_request("co to jest Linux"), "question")
        self.assertEqual(safety.classify_request("no i tak dalej"), "unknown")

    def test_is_unhandled_action(self):
        self.assertTrue(safety.is_unhandled_action("uruchom aktualizację"))
        self.assertFalse(safety.is_unhandled_action("co to jest Linux"))


if __name__ == "__main__":
    unittest.main()
