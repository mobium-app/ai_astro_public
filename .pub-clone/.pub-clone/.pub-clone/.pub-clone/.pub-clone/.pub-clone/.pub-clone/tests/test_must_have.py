"""Testy komend „must-have" (`/etc/astro-secrets/komendy_must-have`): głosowe, deterministyczne.

Sprawdzamy routing i treść odpowiedzi bez realnego I/O (tam, gdzie trzeba — mocki).
"""

import os
import tempfile
import unittest
from unittest import mock

from astro import backends as B
from astro import config, memory, wifi
from astro.core import Agent, dispatch, must_have
from astro.core import extras, fast_tools, profiling
from astro.safety import Confirmer, normalize_command, normalize_facts
from astro.tools import ToolContext, registry


class ScriptedBackend(B.Backend):
    name = "cpu"
    capabilities = {"chat", "tools", "json", "plan"}

    def ready(self):
        return True

    def run(self, messages, **kw):
        return B.BackendResult(text="Odpowiedź modelu.")


def make_agent(auto=False):
    breg = B.BackendRegistry()
    breg.register(ScriptedBackend())
    mem = memory.Memory(os.path.join(tempfile.mkdtemp(), "m.db"))
    ctx = ToolContext(settings=config, memory=mem, confirmer=Confirmer(auto=auto),
                      registry=registry, backends=breg)
    return Agent(backends=breg, registry=registry, memory=mem, ctx=ctx)


class TestRouting(unittest.TestCase):
    def test_abort(self):
        r = must_have.handle("przerwij", make_agent())
        self.assertEqual(r[1], "abort")

    def test_feedback(self):
        self.assertEqual(must_have.handle("źle", make_agent())[1], "feedback-neg")
        self.assertEqual(must_have.handle("super, tak trzymaj", make_agent())[1], "feedback-pos")

    def test_feedback_neg_records_lesson(self):
        agent = make_agent()
        before = agent.memory.lesson_count()
        must_have.handle("źle", agent)
        self.assertGreater(agent.memory.lesson_count(), before)
        self.assertTrue(any("błędn" in lesson for lesson in agent.memory.recent_lessons(3)))

    def test_affection(self):
        self.assertEqual(must_have.handle("lubisz mnie", make_agent())[1], "affection")

    def test_nearby_intent_phrasings(self):
        # Skrypty „najbliższy obiekt" (must-have): różne szyki i rodzaje z listy użytkownika.
        for p in ("najbliższy paczkomat", "podaj adres najbliższej apteki", "gdzie jest paczkomat",
                  "sklep spożywczy w pobliżu", "najbliższa siłownia", "najbliższy bank",
                  "gdzie najbliższa poczta", "najbliższy szpital"):
            self.assertEqual(must_have.intent(p), "nearby", p)

    def test_context_intent_variants(self):        # STT: „pamięta" (bez „sz") i szyk „sprawdź czy pamięta kontekst" (uwaga żywa 2026-09-28).
        for p in ("czy pamietasz kontekst", "sprawdz czy pamieta kontekst", "ostatni kontekst",
                  "ile pamietasz", "stan kontekstu", "pamiec kontekstu", "co pamietasz"):
            self.assertEqual(must_have.intent(p), "context", p)
        r = must_have.handle("sprawdz czy pamieta kontekst", make_agent())
        self.assertEqual(r[1], "context")
        self.assertIn("kontekst", r[0].lower())

    def test_relation_command(self):
        r = must_have.handle("nasza relacja", make_agent())
        self.assertEqual(r[1], "relation")
        self.assertTrue(r[0])
        self.assertEqual(must_have.intent("jak dlugo sie znamy"), "relation")

    def test_recipe(self):
        r = must_have.handle("zaproponuj obiad", make_agent())
        self.assertEqual(r[1], "recipe")
        self.assertTrue(r[0])

    def test_install_asks_without_name(self):
        r = must_have.handle("instaluj program", make_agent())
        self.assertEqual(r[1], "install")
        self.assertIn("jaką", r[0].lower())

    def test_install_creates_confirmation(self):
        agent = make_agent()
        out = dispatch("instaluj aplikację htop", agent)
        self.assertEqual(out.route, "install")
        conf = agent.ctx.confirmer
        self.assertIsNotNone(conf.pending)
        self.assertEqual(conf.pending["kind"], "system_task")
        cmd = conf.pending["payload"]["steps"][0]["command"]
        self.assertIn("apt-get install -y htop", cmd)


class TestInternetEdges(unittest.TestCase):
    def test_own_ip(self):
        sample = ("1: lo inet 127.0.0.1/8 scope host lo\n"
                  "2: wlan0 inet 192.168.0.245/24 brd 192.168.0.255 scope global wlan0")
        with mock.patch.object(must_have, "_run", return_value=(0, sample)):
            r = must_have.handle("podaj swoje ip", make_agent())
        self.assertEqual(r[1], "ip")
        self.assertIn("192.168.0.245", r[0])

    def test_remote_resources(self):
        with mock.patch.object(must_have, "_run", side_effect=[(0, "DRZEWKO"), (0, "Podsumowanie")]):
            r = must_have.handle("pokaż zasoby zdalne", make_agent())
        self.assertEqual(r[1], "remote-usage")
        self.assertIn("Podsumowanie", r[0])

    def test_opencode_missing(self):
        with mock.patch.object(must_have, "_opencode_path", return_value=None):
            r = must_have.handle("otwórz opencode", make_agent())
        self.assertIn("nie znalaz", r[0].lower())

    def test_nearby_uses_location(self):
        agent = make_agent()
        agent.memory.profiles.replace({"city": "Poznań"}, source="test")
        with mock.patch("astro.tools.web.nearby_places_text",
                        return_value="Najbliższe bankomaty dla Poznania: X (100 m).") as fn:
            r = must_have.handle("podaj adres najbliższego bankomatu", agent)
        self.assertEqual(r[1], "nearby")
        self.assertIn("bankomat", r[0].lower())
        self.assertEqual(fn.call_args[0][0], "bankomat")


class TestSystemFastPaths(unittest.TestCase):
    def test_time_is_fast_only_time(self):
        agent = make_agent()
        out = dispatch("która godzina", agent)
        self.assertEqual(out.route, "fast")
        self.assertIn("godzin", out.reply.lower())

    def test_update_sources(self):
        self.assertEqual(fast_tools.update_action(normalize_facts("aktualizuj źródła")), "update")
        self.assertEqual(fast_tools.update_action(normalize_facts("aktualizuj aplikacje")), "full")

    def test_report_generuj(self):
        self.assertTrue(fast_tools.REPORT_RE.search(normalize_facts("generuj raport zasoby")))

    def test_update_programs(self):
        self.assertEqual(fast_tools.update_action(normalize_facts("aktualizuj programy")), "full")

    def test_volume_phrase_variants(self):
        # 1:1 z plikiem must-have + potoczny wariant „podaj głośność".
        for text in ("jaka głośność", "jaki poziom dźwięku", "jaki dźwięk", "podaj głośność"):
            self.assertTrue(fast_tools.VOLUME_RE.search(normalize_facts(text)), text)

    def test_ip_stt_variants(self):
        # Whisper dyktuje „IP" literami („i b"/„i p") albo fonetycznie po polsku („aj pi").
        for text in ("podaj ip", "podaj i b", "podaj i p", "moje ip", "adres i b",
                     "wyświetl ip", "wyświetl i p", "pokaż i p",
                     "podaj aj pi", "aj pi", "Po tej ipa", "podaj i", "podaj i pa"):
            self.assertEqual(must_have.intent(text), "ip", text)

    def test_phonetic_english_terms(self):
        # Użytkownik zapisuje angielskie nazwy fonetycznie: „aj pi" = IP, „si pi ju" = CPU,
        # „waj faj" = Wi-Fi, „opencołd" = opencode.
        self.assertEqual(fast_tools.INFO_RE.search(
            normalize_command("temperatura si pi ju")) is not None, True)
        self.assertEqual(must_have.intent("otworz opencołd"), "launch")
        self.assertEqual(must_have.intent("opencołd"), "launch")
        self.assertEqual(must_have.intent("opencoat"), "launch")
        self.assertEqual(wifi.intent("wyłącz waj faj").get("action"), "disconnect")

    def test_podaj_glosnosc_route(self):
        with mock.patch.object(extras, "volume_get", return_value=80), \
             mock.patch.object(extras, "volume_set"):
            out = dispatch("podaj głośność", make_agent())
        self.assertEqual(out.route, "fast")
        self.assertIn("80", out.reply)

    def test_profile_zbieraj_dane(self):
        self.assertTrue(profiling.TRIGGER_RE.search(normalize_facts("zbieraj dane")))

    def test_volume_step_and_floor(self):
        with mock.patch.object(extras, "volume_get", return_value=50), \
             mock.patch.object(extras, "volume_set") as vs:
            extras.volume_text(normalize_facts("głośniej"))
            vs.assert_called_with(70)
        with mock.patch.object(extras, "volume_get", return_value=100), \
             mock.patch.object(extras, "volume_set") as vs:
            extras.volume_text(normalize_facts("głośniej"))
            vs.assert_called_with(100)
        with mock.patch.object(extras, "volume_get", return_value=30), \
             mock.patch.object(extras, "volume_set") as vs:
            extras.volume_text(normalize_facts("ciszej"))
            vs.assert_called_with(20)
        with mock.patch.object(extras, "volume_get", return_value=20), \
             mock.patch.object(extras, "volume_set") as vs:
            extras.volume_text(normalize_facts("ciszej"))
            vs.assert_called_with(20)


class TestCurrency(unittest.TestCase):
    def test_rate_online(self):
        sample = {"rates": [{"mid": 4.05, "effectiveDate": "2026-09-22"}]}
        with mock.patch.object(extras, "_get_json", return_value=sample), \
             mock.patch.object(extras, "_save_currency_cache"):
            out = extras.currency_text("aktualny kurs dolara")
        self.assertIn("dolara amerykańskiego", out)
        self.assertIn("4,05", out)

    def test_conversion_amount(self):
        sample = {"rates": [{"mid": 4.0, "effectiveDate": "2026-09-22"}]}
        with mock.patch.object(extras, "_get_json", return_value=sample), \
             mock.patch.object(extras, "_save_currency_cache"):
            out = extras.currency_text("przelicz 100 dolarow")
        self.assertIn("100", out)
        self.assertIn("400", out)

    def test_offline_uses_cache(self):
        cache = {"EUR": {"rate": 4.25, "date": "2026-09-20"}}
        with mock.patch.object(extras, "_get_json", side_effect=Exception("offline")), \
             mock.patch.object(extras, "_load_currency_cache", return_value=cache):
            out = extras.currency_text("kurs euro")
        self.assertIn("4,25", out)
        self.assertIn("z pamięci", out)

    def test_route_currency(self):
        sample = {"rates": [{"mid": 4.0, "effectiveDate": "2026-09-22"}]}
        with mock.patch.object(extras, "_get_json", return_value=sample), \
             mock.patch.object(extras, "_save_currency_cache"):
            out = dispatch("aktualny kurs dolara", make_agent())
        self.assertEqual(out.route, "fast")
        self.assertIn("zł", out.reply)

    def test_no_currency(self):
        self.assertIsNone(extras.currency_text("jaka jest pogoda w Poznaniu"))


class FakeRemote(B.Backend):
    name = "remote"
    capabilities = {"chat", "tools", "json", "plan", "fresh"}

    def ready(self):
        return True

    def run(self, messages, **kw):
        return B.BackendResult(text="REMOTE")


class TestSafetyRefuse(unittest.TestCase):
    def test_refuse_destructive(self):
        out = dispatch("usuń wszystkie dane", make_agent())
        self.assertEqual(out.route, "refuse")
        self.assertIn("danych", out.reply)

    def test_warn_prepended(self):
        out = dispatch("usuń plik notatka.txt", make_agent())
        self.assertNotEqual(out.route, "refuse")
        self.assertTrue(out.reply.lower().startswith("uwaga"))

    def test_commands_never_remote(self):
        reg = B.BackendRegistry()
        reg.register(ScriptedBackend())
        reg.register(FakeRemote())
        names = [b.name for b in reg.order("tools", local_only=True)]
        self.assertIn("cpu", names)
        self.assertNotIn("remote", names)


class TestInitiativeRouting(unittest.TestCase):
    def test_quiet_mode_command_routes(self):
        with mock.patch("astro.core.initiative.Initiative") as M:
            inst = M.return_value
            out = dispatch("tryb cichy", make_agent())
        self.assertEqual(out.route, "initiative-quiet")
        inst.set_quiet.assert_called_once_with(True)

    def test_resume_talking_routes(self):
        with mock.patch("astro.core.initiative.Initiative") as M:
            inst = M.return_value
            out = dispatch("wróć do rozmowy", make_agent())
        self.assertEqual(out.route, "initiative-loud")
        inst.set_quiet.assert_called_once_with(False)


class TestWifiNumbered(unittest.TestCase):
    ROWS = [{"ssid": "Kapibara_2G", "signal": 90, "security": "WPA2"},
            {"ssid": "Dom", "signal": 50, "security": "--"}]

    def test_scan_numbered_and_connect(self):
        with mock.patch.object(wifi, "available", return_value=True), \
             mock.patch.object(wifi, "scan", return_value=self.ROWS), \
             mock.patch.object(wifi.mirror, "wall_write"):
            text = wifi.scan_text()
        self.assertIn("1. Kapibara_2G", text)
        self.assertIn("2. Dom", text)
        ssid, err = wifi.connect_by_index(2)
        self.assertEqual(ssid, "Dom")
        self.assertEqual(err, "")
        _ssid, err2 = wifi.connect_by_index(9)
        self.assertTrue(err2)

    def test_dispatch_connect_by_number(self):
        agent = make_agent()
        with mock.patch.object(wifi, "available", return_value=True), \
             mock.patch.object(wifi, "scan", return_value=self.ROWS):
            wifi.scan_numbered()
            out = dispatch("połącz z siecią numer 1", agent)
        self.assertIn(out.route, ("wifi-password", "wifi"))
        self.assertEqual(getattr(agent.ctx, "wifi_pending", None), {"ssid": "Kapibara_2G"})

    def test_disconnect_leave_network(self):
        i = wifi.intent("wyjdź z sieci")
        self.assertEqual((i or {}).get("action"), "disconnect")


class TestVoiceProfile(unittest.TestCase):
    def setUp(self):
        from astro.audio import voice_style
        self.tmp = tempfile.mkdtemp()
        self._patch = mock.patch.object(config, "RUNTIME_DIR", self.tmp)
        self._patch.start()
        voice_style._profile_cache.update(mtime=None, profile=None)

    def tearDown(self):
        self._patch.stop()
        from astro.audio import voice_style
        voice_style._profile_cache.update(mtime=None, profile=None)

    def test_clean_command_sets_clean(self):
        from astro.audio import voice_style
        r = must_have.handle("czysty głos", make_agent())
        self.assertEqual(r[1], "voice-profile")
        self.assertEqual(voice_style.load_profile(), "clean")
        self.assertEqual(voice_style._base_pitch(), "")

    def test_robot_command_sets_robot(self):
        from astro.audio import voice_style
        r = must_have.handle("włącz głos robocika", make_agent())
        self.assertEqual(r[1], "voice-profile")
        self.assertEqual(voice_style.load_profile(), "robocik")
        self.assertTrue(voice_style._base_pitch())

    def test_volume_command_not_hijacked(self):
        # „głośność" nie może być łapane jako profil głosu (obsługuje to fast-tools).
        self.assertEqual(must_have.intent("wyłącz głośność"), "")
        self.assertEqual(must_have.intent("włącz głośność"), "")


    def test_abort_includes_koniec(self):
        for t in ("stop", "koniec", "przerwij", "zatrzymaj"):
            self.assertEqual(must_have.intent(t), "abort", t)

    def test_feedback_pos_includes_spoko(self):
        for t in ("dobrze", "spoko", "super", "okej"):
            self.assertEqual(must_have.intent(t), "feedback-pos", t)

    def test_mode_aliases(self):
        self.assertEqual(must_have.intent("tryb lokalny"), "mode-offline")
        self.assertEqual(must_have.intent("tryb płatny"), "mode-premium")

    def test_vision_aliases(self):
        self.assertEqual(must_have.intent("rozejrzyj się"), "vision-scene")
        self.assertEqual(must_have.intent("znasz go"), "vision-who")
        self.assertEqual(must_have.intent("ile ludzi"), "vision-who")


if __name__ == "__main__":
    unittest.main()
