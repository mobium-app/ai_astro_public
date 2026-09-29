"""Testy kosmetyki mowy (port z run_tests.py)."""

import unittest

from astro import audio


class TestSpeakable(unittest.TestCase):
    def test_contains(self):
        self.assertIn("godzina", audio.speakable("08:47"))
        self.assertIn("numer", audio.speakable("#1"))
        self.assertIn("przecinek", audio.speakable("75.7"))
        self.assertIn("gigabajt", audio.speakable("10 GB"))

    def test_no_symbol_names(self):
        self.assertNotIn("ukośnik", audio.speakable("$HOME"))
        self.assertNotIn("małpa", audio.speakable("jan@example.com"))
        self.assertNotIn("kratka", audio.speakable("#hashtag"))
        self.assertNotIn("daszek", audio.speakable("2^3"))
        self.assertNotIn("tylda", audio.speakable("~x"))
        self.assertNotIn("pionowa", audio.speakable("a|b"))
        self.assertNotIn("równa", audio.speakable("x = y"))
        self.assertNotIn("plus", audio.speakable("2+2"))

    def test_lexicon_acronyms_and_names(self):
        # Leksykon wymowy: akronimy dokładne (wielkość liter) + nazwy własne.
        self.assertIn("i pe", audio.prepare_speech("sprawdź IP"))
        self.assertIn("ce pe u", audio.prepare_speech("temperatura CPU"))
        self.assertIn("hajlo", audio.prepare_speech("stan Hailo"))
        self.assertIn("dżejson", audio.prepare_speech("plik JSON"))
        # Małe „nas" to zwykłe słowo — leksykon go nie rusza.
        self.assertIn("nas", audio.prepare_speech("do nas wróć"))

    def test_lexicon_module(self):
        from astro.audio import lexicon
        upper, words = lexicon.load_lexicon()
        self.assertTrue(upper and words)
        self.assertEqual(lexicon.apply_lexicon("CPU i Hailo"), "ce pe u i hajlo")

    def test_pauses_inserted(self):
        self.assertIn(", ale", audio.speakable("Zrobiłam to ale wynik jest zły"))
        self.assertIn(", jednak", audio.speakable("Próbowałam jednak się nie udało"))
        self.assertTrue(audio.speakable("Uwaga pada deszcz").startswith("Uwaga, "))
        # istniejący przecinek nie jest dublowany
        self.assertNotIn(",,", audio.speakable("Zrobiłam to, ale wynik jest zły"))

    def test_punctuation_preserved(self):
        out = audio.speakable("Idź, proszę. Naprawdę?")
        self.assertIn(",", out)
        self.assertIn(".", out)
        self.assertIn("?", out)

    def test_number_noun_agreement(self):
        self.assertIn("5 plików", audio.speakable("5 plik"))
        self.assertIn("2 błędy", audio.speakable("2 błąd"))
        self.assertIn("3 osoby", audio.speakable("3 osoba"))

    def test_temporal_numbers_spelled(self):
        self.assertIn("za pięć minut", audio.speakable("za 5 minut"))
        self.assertIn("za dwie godziny", audio.speakable("za 2 godziny"))
        self.assertIn("dziesięć minut temu", audio.speakable("10 minut temu"))
        self.assertIn("jedną godzinę", audio.speakable("1 godzinę"))
        self.assertIn("dwa lata", audio.speakable("2 rok"))
        self.assertIn("pięć miesięcy", audio.speakable("5 miesiąc"))
        self.assertIn("jedna godzina", audio.speakable("1 godzina"))

    def test_ordinals(self):
        self.assertIn("pierwsze miejsce", audio.speakable("1. miejsce"))
        self.assertIn("trzecia klasa", audio.speakable("3. klasa"))
        self.assertIn("pierwszy raz", audio.speakable("1. raz"))
        self.assertIn("trzy przecinek jeden cztery", audio.speakable("3.14"))

    def test_case_forms(self):
        self.assertIn("z pięcioma plikami", audio.speakable("z 5 plikami"))
        self.assertIn("o trzech godzinach", audio.speakable("o 3 godzinach"))
        self.assertIn("w dwóch plikach", audio.speakable("w 2 plikach"))

    def test_month_season_locative(self):
        self.assertIn("w styczniu", audio.speakable("w styczeń"))
        self.assertIn("we wrześniu", audio.speakable("we wrzesień"))
        self.assertIn("w maju", audio.speakable("w maj"))
        self.assertIn("w zimie", audio.speakable("w zima"))
        self.assertIn("w lecie", audio.speakable("w lato"))

    def test_roman_century(self):
        self.assertIn("dwudziesty pierwszy wiek", audio.speakable("XXI wiek"))
        self.assertIn("w dwudziestym wieku", audio.speakable("w XX wieku"))
        self.assertIn("dziewiętnasty wiek", audio.speakable("XIX wiek"))

    def test_unit_words(self):
        self.assertIn("pięć kilometrów", audio.speakable("5 km"))
        self.assertIn("sto metrów", audio.speakable("100 m"))
        self.assertIn("dwa kilogramy", audio.speakable("2 kg"))
        self.assertIn("pięćdziesiąt kilometrów na godzinę", audio.speakable("50 km/h"))

    def test_ranges(self):
        self.assertIn("od pięciu do dziesięciu", audio.speakable("od 5 do 10"))

    def test_ordinals_extended(self):
        self.assertIn("piętnasta rocznica", audio.speakable("15. rocznica"))
        self.assertIn("trzydziesta pierwsza edycja", audio.speakable("31. edycja"))

    def test_more_units(self):
        self.assertIn("pięć hektarów", audio.speakable("5 ha"))
        self.assertIn("dwie tony", audio.speakable("2 t"))
        self.assertIn("dziesięć kilowatów", audio.speakable("10 kW"))
        self.assertIn("dwadzieścia metrów kwadratowych", audio.speakable("20 m²"))

    def test_weekdays_accusative(self):
        self.assertIn("w środę", audio.speakable("w środa"))
        self.assertIn("w niedzielę", audio.speakable("w niedziela"))
        self.assertIn("w sobotę", audio.speakable("w sobota"))

    def test_abbrev_round2(self):
        self.assertIn("według", audio.speakable("wg. mnie"))
        self.assertIn("miliardów", audio.speakable("5 mld"))
        self.assertIn("esemes", audio.speakable("SMS"))
        self.assertIn("inżynier", audio.speakable("mgr inż."))

    def test_math_symbols(self):
        self.assertIn("razy", audio.speakable("3 × 4"))
        self.assertIn("podzielić przez", audio.speakable("6 ÷ 2"))
        self.assertIn("około", audio.speakable("≈ 5"))

    def test_century_arabic(self):
        self.assertIn("dwudziesty pierwszy wiek", audio.speakable("21 wiek"))
        self.assertIn("w piętnastym wieku", audio.speakable("w 15 wieku"))

    def test_collective_children(self):
        self.assertIn("dwoje dzieci", audio.speakable("2 dzieci"))
        self.assertIn("pięć dzieci", audio.speakable("5 dzieci"))
        self.assertIn("jedno dziecko", audio.speakable("1 dziecko"))

    def test_half_quarter(self):
        self.assertIn("pół litra", audio.speakable("0,5 l"))
        self.assertIn("ćwierć kilograma", audio.speakable("0,25 kg"))

    def test_dot_time(self):
        self.assertIn("o godzinie piętnastej trzydzieści", audio.speakable("o 15.30"))

    def test_do_genitive(self):
        self.assertIn("do pięciu plików", audio.speakable("do 5 plików"))
        self.assertIn("od jednego do pięciu", audio.speakable("od 1 do 5"))

    def test_per_sec_units(self):
        self.assertIn("metrów na sekundę", audio.speakable("10 m/s"))
        self.assertIn("megabitów na sekundę", audio.speakable("100 Mbps"))
        self.assertIn("jeden gigabit na sekundę", audio.speakable("1 Gbps"))
        self.assertIn("dwie mile na godzinę", audio.speakable("2 mph"))

    def test_energy_and_data_units(self):
        self.assertIn("kilowatogodzin", audio.speakable("5 kWh"))
        self.assertIn("megawatogodziny", audio.speakable("2 MWh"))
        self.assertIn("petabajtów", audio.speakable("5 PB"))
        self.assertIn("bity", audio.speakable("3 bit"))

    def test_symbols_fahrenheit_fractions(self):
        self.assertIn("stopni Fahrenheita", audio.speakable("70°F"))
        self.assertIn("pół", audio.speakable("½"))
        self.assertIn("całodobowo", audio.speakable("24/7"))

    def test_currency_extra(self):
        self.assertIn("franków", audio.speakable("10 CHF"))
        self.assertIn("koron", audio.speakable("200 CZK"))
        self.assertIn("złotych", audio.speakable("5 tys. zł"))

    def test_abbrev_round3(self):
        self.assertIn("generał", audio.speakable("gen. Nowak"))
        self.assertIn("ksiądz", audio.speakable("ks. Jan"))
        self.assertIn("poniedziałek", audio.speakable("pon."))

    def test_emoji_and_arrows_removed(self):
        out = audio.speakable("Gotowe! 😀👍 → tutaj ✅")
        self.assertNotIn("😀", out)
        self.assertNotIn("→", out)
        self.assertNotIn("✅", out)
        self.assertIn("tutaj", out)

    def test_currency_agreement(self):
        self.assertIn("pięć złotych", audio.speakable("5 zł"))
        self.assertIn("dwa złote", audio.speakable("2 zł"))
        self.assertIn("dziesięć dolarów", audio.speakable("10 USD"))
        self.assertIn("trzy euro", audio.speakable("3 EUR"))

    def test_currency_decimals(self):
        self.assertIn("cztery złote pięćdziesiąt groszy", audio.speakable("4,50 zł"))
        self.assertIn("dziesięć złotych", audio.speakable("10,00 zł"))
        self.assertIn("dwa dolary jeden cent", audio.speakable("2,01 USD"))

    def test_punctuation_spacing(self):
        out = audio.speakable("To błąd,brak.Koniec")
        self.assertIn(", ", out)
        self.assertIn(". ", out)

    def test_negative_and_abbrev(self):
        self.assertIn("minus 5", audio.speakable("-5"))
        self.assertIn("2026 roku", audio.speakable("2026 r."))
        self.assertIn("12 tysięcy", audio.speakable("12 tys."))
        self.assertIn("50 groszy", audio.speakable("50 gr"))
        self.assertIn("5-10", audio.speakable("5-10"))

    def test_address_abbrev(self):
        self.assertIn("ulicy Kwiatowej", audio.speakable("ul. Kwiatowej"))
        self.assertIn("alei Róż", audio.speakable("al. Róż"))
        self.assertIn("placu", audio.speakable("pl. Wolności"))

    def test_oclock_locative(self):
        self.assertIn("o godzinie piętnastej trzydzieści", audio.speakable("o 15:30"))
        out = audio.speakable("Godzina 22:00")
        self.assertIn("godzina dwudziesta druga", out)
        self.assertEqual(out.lower().count("godzina"), 1)

    def test_numbers(self):
        self.assertEqual(audio.pl_number(1), "jeden")
        self.assertEqual(audio.pl_number(5), "pięć")
        self.assertEqual(audio.pl_plural(2, ("plik", "pliki", "plików")), "pliki")
        self.assertEqual(audio.pl_plural(5, ("plik", "pliki", "plików")), "plików")

    def test_feminize(self):
        self.assertEqual(audio.feminize("zrobiłem to sam"), "zrobiłam to sama")
        self.assertEqual(audio.feminize("powinienem iść"), "powinnam iść")

    def test_markdown(self):
        self.assertEqual(audio.strip_markdown("**Bold** i `kod`"), "Bold i kod")

    def test_postal_spoken_as_number(self):
        out = audio.speakable("Kod pocztowy to 61-244.")
        self.assertIn("sześćdziesiąt jeden tysięcy dwieście czterdzieści cztery", out)


class TestPrepareSpeech(unittest.TestCase):
    """Pełny łańcuch mowy (TTS): markdown + feminizacja + wymowa liczb/symboli/dat."""

    def test_gender_and_units(self):
        out = audio.prepare_speech("Zrobiłem to: 45.5°C i 12%.")
        self.assertIn("zrobiłam", out.lower())
        self.assertIn("Celsjusza", out)
        self.assertIn("procent", out)

    def test_datetime(self):
        out = audio.prepare_speech("Spotkanie 2026-09-19 o 08:05")
        self.assertIn("dziewiętnastego września 2026", out)
        self.assertIn("o godzinie ósmej pięć", out)

    def test_day_month_ordinal(self):
        self.assertIn("pierwszego maja", audio.speakable("1 maja"))
        self.assertIn("trzeciego marca", audio.speakable("3 marca"))

    def test_full_hour_without_zero(self):
        self.assertIn("godzina piętnasta", audio.speakable("15:00"))
        self.assertNotIn("zero", audio.speakable("15:00"))
        self.assertIn("o godzinie ósmej", audio.speakable("o 8:00"))

    def test_negative_units_and_decimal_percent(self):
        self.assertIn("minus pięć stopni Celsjusza", audio.speakable("-5°C"))
        self.assertIn("trzy przecinek pięć procent", audio.speakable("3,5%"))

    def test_fractions_and_thousands(self):
        self.assertIn("pół", audio.speakable("1/2"))
        self.assertIn("trzy czwarte", audio.speakable("3/4"))
        out = audio.speakable("1 000 osób")
        self.assertNotIn("1 000", out)
        self.assertIn("1000", out)

    def test_more_abbrev(self):
        self.assertIn("tak zwany", audio.speakable("tzw. program"))
        self.assertIn("procent", audio.speakable("50 proc."))
        self.assertIn("milionów", audio.speakable("5 mln"))
        self.assertIn("województwo", audio.speakable("woj. mazowieckie"))

    def test_no_url_and_number_symbol(self):
        out = audio.prepare_speech("Zobacz https://example.com/a oraz #1")
        self.assertNotIn("https", out)
        self.assertIn("numer", out)

    def test_markdown_and_symbols_stripped(self):
        out = audio.prepare_speech("**Ważne** `kod` -> wynik")
        self.assertNotIn("**", out)
        self.assertNotIn("`", out)

    def test_dash_and_spacing(self):
        out = audio.prepare_speech("To jest — powiedzmy — test (ważny).")
        self.assertNotIn("—", out)
        self.assertNotIn(" ,", out)
        self.assertNotIn("(", out)
        self.assertNotIn(")", out)

    def test_feminine_past_forms(self):
        out = audio.prepare_speech("Byłem gotów i byłem sam.")
        self.assertIn("Byłam gotowa", out)
        self.assertIn("byłam sama", out)


if __name__ == "__main__":
    unittest.main()
