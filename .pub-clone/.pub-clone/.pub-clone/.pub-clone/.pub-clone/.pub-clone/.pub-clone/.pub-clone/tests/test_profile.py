"""Testy profilu użytkownika: schemat, magazyn+audyt, wywiad „poznaj mnie", maskowanie."""

import json
import types
import unittest

from astro import mirror
from astro.core import profiling
from astro.memory import Memory
from astro.user import profile as P
from astro.user.intake import ProfileIntake
from astro.user.store import ProfileStore


def make_store():
    return ProfileStore(Memory(":memory:").con)


def make_mem():
    return Memory(":memory:")


def make_agent(mem):
    ctx = types.SimpleNamespace(memory=mem)
    return types.SimpleNamespace(ctx=ctx, memory=mem)


def feed(it, text):
    """Podaje odpowiedź i automatycznie potwierdza read-back („Czy dobrze?")."""
    reply = it.feed(text)
    if "Czy dobrze" in reply:
        reply = it.feed("tak")
    return reply


class TestSchema(unittest.TestCase):
    def test_gender_inference(self):
        self.assertEqual(P.infer_gender("Anna"), "f")
        self.assertEqual(P.infer_gender("Piotr"), "m")
        self.assertEqual(P.infer_gender("Kuba"), "m")

    def test_extract_name(self):
        self.assertEqual(P.extract_name("mam na imię Anna"), "Anna")
        self.assertEqual(P.extract_name("jestem Marek"), "Marek")

    def test_postal_code(self):
        self.assertEqual(P.normalize_value("postal_code", "00950"), "00-950")
        self.assertEqual(P.normalize_value("postal_code", "00 950"), "00-950")

    def test_parse_postal_dictated(self):
        self.assertEqual(P.parse_postal("6-1-244"), "61-244")
        self.assertEqual(P.parse_postal("61 244"), "61-244")
        self.assertEqual(P.parse_postal("zero zero dziewięć pięć zero"), "00-950")
        self.assertEqual(P.parse_postal("61.244"), "61-244")
        self.assertEqual(P.parse_postal("60 000 200 000 sys"), "")
        self.assertEqual(P.parse_postal("64.24"), "")
        self.assertEqual(P.parse_postal("nie wiem"), "")

    def test_validate_enum(self):
        self.assertEqual(P.normalize_value("address_form", "Pani"), "pani")
        ok, val, _ = P.validate("gender_form", "kobieta")
        self.assertTrue(ok)
        self.assertEqual(val, "f")
        ok, _, _ = P.validate("gender_form", "nie wiadomo co")
        self.assertFalse(ok)

    def test_address_form_stt_tolerant(self):
        # Sesja głosowa 2026-09-21: „na te" nie było rozpoznawane jako „na ty".
        self.assertEqual(P.normalize_value("address_form", "na te"), "ty")
        self.assertEqual(P.normalize_value("address_form", "naty"), "ty")
        self.assertEqual(P.normalize_value("address_form", "na tą"), "ty")
        self.assertEqual(P.normalize_value("address_form", "Panie"), "pan")
        self.assertEqual(P.normalize_value("address_form", "Pani"), "pani")
        ok, val, _ = P.validate("address_form", "na te")
        self.assertTrue(ok)
        self.assertEqual(val, "ty")
        ok, _, err = P.validate("address_form", "nie wiem")
        self.assertFalse(ok)
        self.assertIn("na ty", err)

    def test_city_capitalized(self):
        self.assertEqual(P.normalize_value("city", "nowy sącz"), "Nowy Sącz")

    def test_city_stt_corrected(self):
        self.assertEqual(P.normalize_value("city", "Poznani"), "Poznań")
        self.assertEqual(P.normalize_value("city", "Gdans"), "Gdańsk")

    def test_name_stt_corrected(self):
        self.assertEqual(P.normalize_value("preferred_name", "Michau"), "Michał")

    def test_salutation_vocative(self):
        prof = {"preferred_name": "Anna", "address_form": "pani"}
        self.assertEqual(P.salutation(prof), "Pani Anno")
        prof = {"preferred_name": "Marek", "address_form": "pan"}
        self.assertEqual(P.salutation(prof), "Panie Marku")
        prof = {"preferred_name": "Anna", "address_form": "ty"}
        self.assertEqual(P.salutation(prof), "Anno")

    def test_context_excludes_address(self):
        prof = {"preferred_name": "Anna", "address_form": "pani", "city": "Warszawa",
                "address": "Kwiatowa 5", "profession": "lekarka"}
        block = P.context_block(prof)
        self.assertIn("Pani Anno", block)
        self.assertIn("Warszawa", block)
        self.assertNotIn("Kwiatowa", block)

    def test_redact(self):
        self.assertEqual(P.redact("adres Kwiatowa 5 koniec", ["Kwiatowa 5"]),
                         "adres [prywatne] koniec")


class TestStore(unittest.TestCase):
    def test_merge_and_get(self):
        s = make_store()
        s.merge({"preferred_name": "Anna", "city": "Warszawa"})
        self.assertEqual(s.get()["preferred_name"], "Anna")
        self.assertEqual(s.get_field("city"), "Warszawa")

    def test_replace_clears_missing(self):
        s = make_store()
        s.replace({"preferred_name": "Anna", "city": "Warszawa", "hobbies": ["rower"]})
        s.replace({"preferred_name": "Anna"})
        self.assertIsNone(s.get_field("city"))
        self.assertIsNone(s.get_field("hobbies"))

    def test_history_audit(self):
        s = make_store()
        s.merge({"city": "Warszawa"})
        s.merge({"city": "Kraków"})
        hist = s.history()
        self.assertTrue(any(h["key"] == "city" for h in hist))
        self.assertTrue(any(h["new_value"] and "Krak" in h["new_value"] for h in hist))

    def test_forget(self):
        s = make_store()
        s.replace({"preferred_name": "Anna", "address": "Kwiatowa 5"})
        self.assertEqual(s.forget("address"), 1)
        self.assertIsNone(s.get_field("address"))
        s.forget()
        self.assertEqual(s.get(), {})

    def test_export_json(self):
        s = make_store()
        s.merge({"preferred_name": "Anna"})
        data = s.export()
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["profile"]["preferred_name"], "Anna")
        json.dumps(data)

    def test_private_redacted_in_mirror(self):
        s = make_store()
        s.merge({"address": "Kwiatowa 5"})
        self.assertEqual(mirror.redact("jadę na Kwiatowa 5"), "jadę na [prywatne]")
        mirror.set_redactions([])

    def test_masked_summary_hides_address(self):
        s = make_store()
        s.replace({"preferred_name": "Anna", "address": "Kwiatowa 5"})
        lines = "\n".join(s.summary(masked=True))
        self.assertNotIn("Kwiatowa", lines)


class TestIntake(unittest.TestCase):
    def test_full_flow(self):
        it = ProfileIntake()
        q = it.start()
        self.assertIn("imię", q)
        for a in ("Anna", "pani", "Warszawa", "Kwiatowa 5", "00-950", "lekarka",
                  "rower, książki", "mąż Piotr", "krótko", "od 22 do 7"):
            feed(it, a)
        self.assertEqual(it.phase, "confirm")
        self.assertTrue(it.active)
        r = it.feed("potwierdzam")
        self.assertTrue(it.confirmed)
        self.assertFalse(it.active)
        self.assertEqual(it.answers["preferred_name"], "Anna")
        self.assertEqual(it.answers["gender_form"], "f")
        self.assertEqual(it.answers["hobbies"], ["rower", "książki"])

    def test_readback_and_correction(self):
        it = ProfileIntake()
        it.start()
        r = it.feed("Michau")
        self.assertIn("Czy dobrze", r)
        r = it.feed("nie, Michał")
        self.assertEqual(it.answers["preferred_name"], "Michał")

    def test_skip(self):
        it = ProfileIntake()
        it.start()
        feed(it, "Anna")
        it.feed("pomiń")
        self.assertNotIn("address_form", it.answers)
        self.assertEqual(it.answers["preferred_name"], "Anna")

    def test_cancel(self):
        it = ProfileIntake()
        it.start()
        r = it.feed("anuluj")
        self.assertFalse(it.active)
        self.assertTrue(it.cancelled)
        self.assertIn("Anulowałam", r)

    def test_cancel_stt_tolerant(self):
        it = ProfileIntake()
        it.start()
        for a in ("Anna", "pani", "Warszawa", "Kwiatowa 5", "00-950", "lekarka",
                  "rower", "pomiń", "pomiń", "pomiń"):
            feed(it, a)
        self.assertEqual(it.phase, "confirm")
        r = it.feed("Anonui")
        self.assertTrue(it.cancelled)
        self.assertIn("Anulowałam", r)

    def test_confirm_stt_tolerant(self):
        it = ProfileIntake()
        it.start()
        for a in ("Anna", "pani", "Warszawa", "Kwiatowa 5", "00-950", "lekarka",
                  "rower", "pomiń", "pomiń", "pomiń"):
            feed(it, a)
        r = it.feed("Potwierzam")
        self.assertTrue(it.confirmed, r)

    def test_confirm_hard_stt_errors(self):
        for word in ("Potirten", "Podwierdan"):
            it = ProfileIntake()
            it.start()
            for a in ("Anna", "pani", "Warszawa", "Kwiatowa 5", "00-950", "lekarka",
                      "rower", "pomiń", "pomiń", "pomiń"):
                feed(it, a)
            it.feed(word)
            self.assertTrue(it.confirmed, f"{word}: {it.phase}")

    def test_finish_early(self):
        it = ProfileIntake()
        it.start()
        it.feed("Anna")
        it.feed("wystarczy")
        self.assertEqual(it.phase, "confirm")

    def test_mode_update(self):
        it = ProfileIntake(existing={"preferred_name": "Anna"})
        q = it.start()
        self.assertIn("nadpisz", q)
        it.feed("zaktualizuj")
        self.assertNotIn("preferred_name", it.order)
        self.assertIn("city", it.order)

    def test_correction(self):
        it = ProfileIntake()
        it.start()
        it.feed("nie, Katarzyna")
        it.feed("tak")
        self.assertEqual(it.answers["preferred_name"], "Katarzyna")

    def test_correct_field_in_summary(self):
        it = ProfileIntake()
        it.start()
        for a in ("Anna", "pani", "Warszawa", "Kwiatowa 5", "00-950", "lekarka",
                  "rower", "pomiń", "pomiń", "pomiń"):
            feed(it, a)
        self.assertEqual(it.phase, "confirm")
        r = it.feed("popraw miasto")
        self.assertIn("nową wartość", r)
        feed(it, "Gdańsk")
        self.assertEqual(it.phase, "confirm")
        self.assertEqual(it.answers["city"], "Gdańsk")

    def test_correct_postal_in_summary(self):
        it = ProfileIntake()
        it.start()
        for a in ("Anna", "pani", "Warszawa", "Kwiatowa 5", "00-950", "lekarka",
                  "rower", "pomiń", "pomiń", "pomiń"):
            feed(it, a)
        it.feed("popraw kod pocztowy")
        feed(it, "31 500")
        self.assertEqual(it.answers["postal_code"], "31-500")

    def test_correct_unknown_field(self):
        it = ProfileIntake()
        it.start()
        for a in ("Anna", "pani", "Warszawa", "Kwiatowa 5", "00-950", "lekarka",
                  "rower", "pomiń", "pomiń", "pomiń"):
            feed(it, a)
        r = it.feed("popraw kolor")
        self.assertIn("Które pole", r)


class TestProfiling(unittest.TestCase):
    def test_trigger_and_commit(self):
        mem = make_mem()
        agent = make_agent(mem)
        reply, route = profiling.handle("poznaj mnie", agent)
        self.assertEqual(route, "profile-intake")
        self.assertIn("imię", reply)
        self.assertIsNotNone(agent.ctx.profile_intake)
        for txt in ("Anna", "pani", "Warszawa", "pomiń", "pomiń", "lekarka",
                    "pomiń", "pomiń", "pomiń", "pomiń"):
            reply, _ = profiling.handle(txt, agent)
            if "Czy dobrze" in reply:
                profiling.handle("tak", agent)
        r, route = profiling.handle("potwierdzam", agent)
        self.assertEqual(route, "profile")
        self.assertEqual(mem.profiles.get_field("preferred_name"), "Anna")
        self.assertIsNone(agent.ctx.profile_intake)

    def test_query(self):
        mem = make_mem()
        mem.profiles.replace({"preferred_name": "Anna", "address": "Kwiatowa 5"})
        agent = make_agent(mem)
        reply, route = profiling.handle("co o mnie wiesz", agent)
        self.assertEqual(route, "profile")
        self.assertIn("Anna", reply)
        self.assertNotIn("Kwiatowa", reply)

    def test_query_empty(self):
        agent = make_agent(make_mem())
        reply, _ = profiling.handle("co o mnie wiesz", agent)
        self.assertIn("Nie znam", reply)

    def test_trigger_stt_tolerant(self):
        agent = make_agent(make_mem())
        reply, route = profiling.handle("Poznaje mnie", agent)
        self.assertEqual(route, "profile-intake")

    def test_repeat_trigger_reasks_question(self):
        # Sesja głosowa 2026-09-21: powtórzone „poznaj mnie" było zapisywane jako imię.
        agent = make_agent(make_mem())
        profiling.handle("poznaj mnie", agent)
        reply, route = profiling.handle("Poznaj mnie", agent)
        self.assertEqual(route, "profile-intake")
        # Krótkie pytanie bez monotonnej numeracji (2026-09-27).
        self.assertIn("Jak mam się do Ciebie zwracać", reply)
        self.assertEqual(agent.ctx.profile_intake.answers, {})

    def test_command_interrupts_intake(self):
        # Komendy must-have muszą działać także w trakcie wywiadu (lista: „ZAWSZE”).
        import sys
        import astro.core.dispatch  # noqa: F401
        d = sys.modules["astro.core.dispatch"]
        agent = make_agent(make_mem())
        d.dispatch("poznaj mnie", agent)
        res = d.dispatch("która godzina", agent)
        self.assertEqual(res.route, "fast")
        self.assertIn("godzina", res.reply.lower())
        self.assertIsNotNone(agent.ctx.profile_intake)
        # Wywiad nadal przyjmuje odpowiedzi (Q1: imię).
        reply, route = profiling.handle("Anna", agent)
        self.assertEqual(route, "profile-intake")
        self.assertNotIn("Nie rozpoznałam", reply)

    def test_command_like_name_rejected(self):
        it = ProfileIntake()
        it.start()
        reply = it.feed("jaka głośność")
        self.assertIn("polecenie", reply)
        self.assertNotIn("preferred_name", it.answers)

    def test_forget_interrupts_intake(self):
        mem = make_mem()
        agent = make_agent(mem)
        profiling.handle("poznaj mnie", agent)
        reply, route = profiling.handle("zapomnij o mnie", agent)
        self.assertEqual(route, "profile-forget-ask")
        self.assertIsNone(agent.ctx.profile_intake)
        _, route = profiling.handle("potwierdzam", agent)
        self.assertEqual(route, "profile-forget")

    def test_forget_confirmation(self):
        mem = make_mem()
        mem.profiles.replace({"preferred_name": "Anna"})
        agent = make_agent(mem)
        _, route = profiling.handle("zapomnij o mnie", agent)
        self.assertEqual(route, "profile-forget-ask")
        _, route = profiling.handle("potwierdzam", agent)
        self.assertEqual(route, "profile-forget")
        self.assertEqual(mem.profiles.get(), {})

    def test_none_for_other(self):
        agent = make_agent(make_mem())
        self.assertIsNone(profiling.handle("jaka pogoda", agent))

    def test_dispatch_routes_profile(self):
        import sys
        import astro.core.dispatch  # noqa: F401
        d = sys.modules["astro.core.dispatch"]
        mem = make_mem()
        agent = make_agent(mem)
        res = d.dispatch("poznaj mnie", agent)
        self.assertEqual(res.route, "profile-intake")


if __name__ == "__main__":
    unittest.main()
