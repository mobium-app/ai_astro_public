"""Testy bezpieczeństwa (port + rozszerzenie)."""

import unittest

from astro import safety


class TestClassify(unittest.TestCase):
    def test_command(self):
        for text in ("zainstaluj pakiet htop",
                     "sprawdź temperaturę procesora i wolne miejsce na dysku",
                     "zapisz notatkę o kawie",
                     "uruchom aktualizację repozytoriów"):
            self.assertEqual(safety.classify_request(text), "command", text)

    def test_question(self):
        for text in ("co to jest Linux",
                     "jak się masz",
                     "wyjaśnij mi działanie DNS",
                     "czym jest inflacja?"):
            self.assertEqual(safety.classify_request(text), "question", text)

    def test_unknown(self):
        self.assertEqual(safety.classify_request("no i tak dalej"), "unknown")

    def test_chat_text_tasks(self):
        # CZAT: zadania na tekście idą do modelu (nie wykonujemy komend).
        for text in ("streść ten tekst", "przetłumacz to na angielski", "popraw ten tekst"):
            self.assertEqual(safety.classify_request(text), "chat", text)

    def test_theory_questions_stay_questions(self):
        # Teoria/pytania NIE mogą zostać przeklasyfikowane na „chat" (tor remote-learn).
        for text in ("wyjaśnij mi działanie DNS", "wyjaśnij krok po kroku jak działa fotosynteza"):
            self.assertEqual(safety.classify_request(text), "question", text)


class TestCommands(unittest.TestCase):
    def test_is_safe_command(self):
        self.assertTrue(safety.is_safe_command("ls -la /tmp"))
        self.assertTrue(safety.is_safe_command("df -h"))
        self.assertTrue(safety.is_safe_command("systemctl status ssh"))
        self.assertFalse(safety.is_safe_command("ls; rm -rf /"))
        self.assertFalse(safety.is_safe_command("rm -rf /"))
        self.assertFalse(safety.is_safe_command("cat ~/.ssh/id_rsa"))

    def test_agent_readonly_ok(self):
        self.assertTrue(safety.agent_readonly_ok("ps aux | head"))
        self.assertFalse(safety.agent_readonly_ok("rm -rf /tmp/x"))
        self.assertFalse(safety.agent_readonly_ok("ls; reboot"))
        self.assertFalse(safety.agent_readonly_ok("sed -i s/a/b/ plik"))

    def test_confirm_re(self):
        self.assertTrue(safety.CONFIRM_RE.search("potwierdzam"))
        self.assertTrue(safety.CONFIRM_RE.search("tak, zatwierdzam"))
        self.assertTrue(safety.CONFIRM_RE.search("autoryzuję"))
        self.assertFalse(safety.CONFIRM_RE.search("wykonaj to"))
        self.assertTrue(safety.CONFIRM_ONLY_RE.match("potwierdzam"))
        self.assertFalse(safety.CONFIRM_ONLY_RE.match("nie mam nic do potwierdzenia"))

    def test_blocked(self):
        self.assertTrue(safety.is_blocked_command("sudo reboot"))
        self.assertFalse(safety.is_blocked_command("ls -la"))


class TestSecrets(unittest.TestCase):
    def test_sensitive_path(self):
        self.assertTrue(safety.is_sensitive_path("~/.ssh/id_rsa"))
        self.assertTrue(safety.is_sensitive_path("$HOME/.git-credentials"))
        self.assertFalse(safety.is_sensitive_path("/tmp/plik.txt"))

    def test_private_url(self):
        self.assertTrue(safety.is_private_url("http://192.168.0.2"))
        self.assertTrue(safety.is_private_url("http://127.0.0.1:11434"))
        self.assertTrue(safety.is_private_url("http://localhost:8080"))
        self.assertTrue(safety.is_private_url("http://router.local"))
        self.assertFalse(safety.is_private_url("https://example.com/x"))


class TestAssess(unittest.TestCase):
    def test_refuse(self):
        verdict, note = safety.assess_user_request("usuń wszystkie dane z dysku")
        self.assertEqual(verdict, "refuse")
        self.assertTrue(note)
        verdict, _ = safety.assess_user_request("wyłącz firewall")
        self.assertEqual(verdict, "refuse")

    def test_warn(self):
        verdict, note = safety.assess_user_request("usuń pliki z katalogu")
        self.assertEqual(verdict, "warn")
        self.assertTrue(note)

    def test_ok(self):
        verdict, note = safety.assess_user_request("sprawdź temperaturę procesora")
        self.assertEqual(verdict, "ok")
        self.assertIsNone(note)


class TestPlans(unittest.TestCase):
    def test_dangerous(self):
        steps = [{"command": "rm -rf / "}]
        self.assertIsNotNone(safety.validate_plan(steps, "cokolwiek"))

    def test_diagnostic_no_install(self):
        steps = [{"command": "apt-get install htop"}]
        self.assertIsNotNone(safety.validate_plan(steps, "zdiagnozuj problem z siecią"))

    def test_clean(self):
        steps = [{"command": "df -h"}, {"command": "uptime"}]
        self.assertIsNone(safety.validate_plan(steps, "sprawdź stan systemu"))

    def test_rejects_command_chaining(self):
        # C1: krok planu nie może łączyć poleceń ani podstawiać wyników.
        for cmd in ("ls; rm -rf /tmp/x", "df -h && reboot", "cat a || wget x",
                    "echo `whoami`", "echo $(id)", "ps aux | grep x; kill 1"):
            self.assertIsNotNone(safety.validate_plan([{"command": cmd}], "zadanie"), cmd)

    def test_allows_simple_pipe(self):
        self.assertIsNone(safety.validate_plan([{"command": "ps aux | head"}], "sprawdź procesy"))


class TestConfirmer(unittest.TestCase):
    def test_auto(self):
        c = safety.Confirmer(auto=True)
        self.assertTrue(c.require_confirm("zrobić?", "test", {}))

    def test_pending_flow(self):
        c = safety.Confirmer(auto=False)
        self.assertFalse(c.require_confirm("zrobić?", "test", {"a": 1}))
        handled, ok, pending = c.answer("potwierdzam")
        self.assertTrue(handled)
        self.assertTrue(ok)
        self.assertEqual(pending["kind"], "test")

    def test_cancel(self):
        c = safety.Confirmer(auto=False)
        c.require_confirm("zrobić?", "test", {})
        handled, ok, _ = c.answer("anuluj")
        self.assertTrue(handled)
        self.assertFalse(ok)

    def test_confirm_stt_tolerant(self):
        # Whisper gubi „d": „Potwierzam"/„Zatwirdzam" muszą potwierdzać (inaczej update przepada).
        for word in ("Potwierzam", "Potwierdzan", "Zatwirdzam", "potwierdzam"):
            c = safety.Confirmer(auto=False)
            c.require_confirm("zrobić?", "test", {})
            handled, ok, pending = c.answer(word)
            self.assertTrue(handled and ok, word)
            self.assertEqual(pending["kind"], "test")
            self.assertIsNone(c.pending)

    def test_new_command_clears_pending(self):
        c = safety.Confirmer(auto=False)
        c.require_confirm("zrobić?", "test", {})
        handled, _, _ = c.answer("jaka głośność")
        self.assertFalse(handled)

    def test_short_yes_is_confirmation(self):
        # Głosowe „Mam to wykonać?" wymaga krótkiego „tak/ok/no/jasne" (nie tylko „potwierdzam").
        for word in ("tak", "Tak", "ta", "tad", "no", "nom", "ok", "okej", "jasne", "zgoda",
                     "dobrze", "potwierdzam"):
            self.assertTrue(safety.is_confirmation(word), word)

    def test_short_no_is_not_confirmation(self):
        for word in ("nie", "anuluj", "stop", "jaka pogoda", ""):
            self.assertFalse(safety.is_confirmation(word), word)


if __name__ == "__main__":
    unittest.main()
