"""Testy dopasowania zniekształconej mowy do znanej komendy must-have (core/command_match)."""

import unittest

from astro.core import command_match as cm


class TestCommandMatch(unittest.TestCase):
    def test_maps_garbled_to_command(self):
        cases = {
            "pokaż zafoby w dalne": "pokaż zasoby zdalne",
            "restaart systemu": "restart systemu",
            "wylancz system": "wyłącz system",
            "scisz glos": "ścisz głos",
            "ktora gozina": "która godzina",
            "pokaż zasoby systemowe": "pokaż zasoby systemowe",
        }
        for garbled, expected in cases.items():
            cmd, score = cm.best(garbled)
            self.assertEqual(cmd, expected, f"{garbled!r} -> {cmd!r} ({score})")
            self.assertGreaterEqual(score, 0.80)

    def test_ignores_non_commands(self):
        for text in ("dlaczego niebo jest niebieskie",
                     "opowiedz mi żart o programistach",
                     "co to jest fotosynteza"):
            cmd, _score = cm.best(text)
            self.assertIsNone(cmd, f"{text!r} nie powinno mapować się na komendę ({cmd!r})")

    def test_commands_baked_in_repo(self):
        self.assertGreaterEqual(len(cm.commands()), 40)

    def test_arrow_format_parsed(self):
        # Nowa forma listy: opis oddzielony „---->", aliasy po „/", slot [.zmienna.].
        import os
        import tempfile
        content = (
            "# legenda\n"
            "## wyłącz system / zamknij system \t----> wyłącza bezpiecznie (shutdown) (potwierdzenie)\n"
            "## instaluj aplikacje [.zmienna.] / instaluj program [.zmienna.] ----> instaluje apk\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write(content)
            path = fh.name
        try:
            cmds = cm._commands(path)
        finally:
            os.unlink(path)
        self.assertIn("wyłącz system", cmds)
        self.assertIn("zamknij system", cmds)
        self.assertIn("instaluj aplikacje", cmds)
        self.assertIn("instaluj program", cmds)
        # Opis NIE może wejść do komendy (brak „---->", „[", „potwierdzenie").
        for c in cmds:
            self.assertNotIn("----", c)
            self.assertNotIn("[", c)
            self.assertNotIn("shutdown", c)

    def test_restore_diacritics(self):
        cases = {
            "wylacz system": "wyłącz system",
            "podaj godzine": "podaj godzinę",
            "scisz glos": "ścisz głos",
            "sprawdz status": "sprawdź status",
            "wyswietl zasoby": "wyświetl zasoby",
        }
        for plain, proper in cases.items():
            self.assertEqual(cm.restore_diacritics(plain), proper, plain)

    def test_canonicalize_remote_alias(self):
        for variant in ("remote", "remont", "zdarne", "remout"):
            self.assertEqual(cm.canonicalize(f"pokaż zasoby {variant}"),
                             "pokaż zasoby zdalne", variant)

    def test_alias_boost_similarity(self):
        # „remote"/„zdalne" znaczą to samo — po aliasach podobieństwo wysokie.
        self.assertGreaterEqual(cm.similarity("pokaż zasoby remote", "pokaz zasoby zdalne"), 0.95)

    def test_diacritic_loss_matches_canon(self):
        # Whisper zgubił ogonki — po rekonstrukcji tekst == kanon (pewne trafienie).
        for got, canon in (("podaj godzine", "podaj godzinę"),
                           ("wyswietl zasoby zdarne", "wyświetl zasoby zdalne")):
            restored = cm.normalize(cm.canonicalize(cm.restore_diacritics(got)))
            self.assertEqual(restored, cm.normalize(canon), got)

    def test_not_a_command_after_alias(self):
        # Aliasy nie mogą zamieniać pytań w komendy.
        cmd, _ = cm.best("opowiedz o zasobach remote w chmurze")
        self.assertIsNone(cmd)

    def test_za_prefix_equivalent(self):
        # „zainstaluj" i „instaluj" to ten sam zamiar (Whisper dodaje „za-").
        for variant in ("zainstaluj program", "zaaktualizuj programy"):
            self.assertTrue(cm.normalize(cm.canonicalize(variant)).startswith(
                cm.normalize(cm.canonicalize(variant))[:1]))
        self.assertEqual(cm.canonicalize("zainstaluj program"), "instaluj program")
        self.assertEqual(cm.canonicalize("zaaktualizuj programy"), "aktualizuj programy")
        self.assertGreaterEqual(cm.similarity("zainstaluj program", "instaluj program"), 0.95)

    def test_variable_prefix_match(self):
        # Komendy ze zmienną [.zmienna.] muszą łapać wypowiedź z PODSTAWIONĄ wartością
        # („…w Poznań", „…google.pl", „…Michał") — prefiks + dowolne słowo (kalibracja 2026-09-30).
        cases = {
            "jaka jest pogoda w Poznań": "jaka jest pogoda w",
            "podaj adres najbliższego bankomatu": "podaj adres najbliższego",
            "adres ip dla google.pl": "adres ip dla",
            "zapamiętaj to jest Michał": "zapamietaj, to jest",
            "zapomnij Kasia": "zapomnij",
            "instaluj aplikacje mc": "instaluj aplikacje",
            "ping 192.168.0.4": "ping",
        }
        for spoken, expected in cases.items():
            cmd, score = cm.best(spoken)
            self.assertEqual(cmd, expected, f"{spoken!r} -> {cmd!r} ({score})")
            self.assertGreaterEqual(score, 0.80, spoken)

    def test_variable_prefix_no_false_positive(self):
        # Prefiks-ze-zmienną NIE łapie pytań niezwiązanych (bez prefiksu komendy).
        for text in ("czy pogoda jutro się poprawi",
                     "co sądzisz o pogodzie w tym roku",
                     "czy pamiętasz co jadłem na obiad"):
            cmd, _ = cm.best(text)
            self.assertIsNone(cmd, f"{text!r} nie powinno mapować się na komendę ({cmd!r})")

    def test_variable_commands_listed(self):
        # Komendy wykonawcze ze zmienną są wykrywane (nie pytania CZAT).
        vc = set(cm.variable_commands())
        self.assertIn("instaluj aplikacje", vc)
        self.assertIn("ping", vc)
        self.assertIn("adres ip dla", vc)
        # Pytanie CZAT ze zmienną NIE jest komendą wykonawczą.
        self.assertNotIn("co to jest", vc)


if __name__ == "__main__":
    unittest.main()
