"""Kosmetyka tekstu mowy: feminizacja i wymowa (port z Ateny, zachowanie 1:1).

B5: pełny podział monolitu `audio/text.py` na pakiet:
* `numbers.py` — liczby, liczebniki, rzymskie, przypadki liczebnika;
* `units.py` — jednostki miary, rzeczowniki/odmiana, waluty, ułamki;
* `dates.py` — daty, godziny, miesiące;
* `lex.py` — skróty, wymowa, symbole, pauzy.
Ten moduł (`__init__`) jest fasadą: orkiestruje `speakable`/`prepare_speech` i re-eksportuje
publiczne nazwy, więc `audio.speakable`/`audio.feminize`/... działają jak dotąd.
"""

import re

from ...safety import normalize_facts
from ..lexicon import apply_lexicon
from ..text_clean import _EMOJI_RE, feminize, strip_markdown  # noqa: F401 (re-eksport)
from .dates import (PL_DAYS_ORD_GEN, PL_DAY_MONTH_RE, PL_HOURS_F, PL_MONTHS_GEN, TTS_DATE_EU,
                    TTS_DATE_ISO, TTS_GODZ_RE, TTS_O_GODZ_RE, TTS_OCLOCK_RE, TTS_POSTAL_RE,
                    TTS_TIME_RE, _GODZ_DOT_RE, _MONTH_LOC, _O_DOT_RE, _W_LOC_RE)
from .lex import TTS_ABBREV, TTS_PRONOUNCE, TTS_SYMBOLS, _ensure_pauses
from .numbers import (NUM_INSTR, NUM_LOC, PL_ONES, TTS_DEC_RE, _CENTURY_RE, _CHILD_RE, _COLLECT,
                      _DO_RE, _GEN, _ORDINAL_M, _ORDINAL_NOUNS, _ORDINAL_RE, _RANGE_RE, _ROMAN_RE,
                      _THOUSANDS_RE, _loc_masculine, _num_words, ordinal_m, pl_number, pl_plural,
                      roman_to_int)
from .units import (CASE_FORMS, COUNT_NOUNS, CURRENCY, FRACTIONS, TEMPORAL_KEYS, TTS_PERCENT_RE,
                    TTS_UNIT_FORMS, TTS_UNIT_RE, _CASE_FORM_TO_KEY, _CASE_RE, _CENT_FORMS,
                    _CURRENCY_DEC_RE, _CURRENCY_RE, _FEMININE_KEYS, _FEMININE_UNITS, _FORM_TO_KEY,
                    _FRACTION_RE, _HALF_RE, _HALF_UNIT_RE, _PER_SEC, _QUARTER_RE, _UNIT_GEN,
                    _UNIT_WORD_RE, _UNIT_WORDS, _unit_key)


def speakable(text):
    if not text:
        return text

    def frac_words(frac):
        return " ".join(PL_ONES[int(c)] if c.isdigit() else c for c in frac)

    def replace_unit(m):
        whole, frac = int(m.group(1)), m.group(2)
        out = pl_number(whole)
        key = m.group(3).upper()
        has_frac = bool(frac and int(frac))
        if has_frac:
            out += " przecinek " + frac_words(frac)
        if key in TTS_UNIT_FORMS:
            forms = TTS_UNIT_FORMS[key]
            out += " " + (forms[3] if has_frac else pl_plural(whole, forms[:3]))
        return out

    def replace_time(m):
        h, mn, sec = int(m.group(1)), int(m.group(2)), m.group(3)
        out = f"godzina {PL_HOURS_F.get(h, pl_number(h))}"
        if mn:
            out += f" {pl_number(mn)}"
        if sec is not None and int(sec):
            out += f" i {pl_number(int(sec))} sekund"
        return out

    def replace_oclock(m):
        h, mn = int(m.group(1)), int(m.group(2))
        if not 0 <= h <= 23 or not 0 <= mn <= 59:
            return m.group(0)
        base = PL_HOURS_F.get(h, pl_number(h))
        locative = " ".join(re.sub(r"a$", "ej", w) for w in base.split())
        tail = f" {pl_number(mn)}" if mn else ""
        return f"o godzinie {locative}{tail}"

    def replace_godz(m):
        h, mn = int(m.group(1)), int(m.group(2))
        if not 0 <= h <= 23 or not 0 <= mn <= 59:
            return m.group(0)
        tail = f" {pl_number(mn)}" if mn else ""
        return f"godzina {PL_HOURS_F.get(h, pl_number(h))}{tail}"

    def replace_decimal(m):
        whole, frac = m.group(1), m.group(2)
        if not int(frac):
            return pl_number(int(whole))
        return f"{pl_number(int(whole))} przecinek {frac_words(frac)}"

    def replace_postal(m):
        return pl_number(int(m.group(1) + m.group(2)))

    def replace_currency(m):
        num, cur = m.group(1), m.group(2).lower()
        forms = CURRENCY.get(cur)
        if not forms:
            return m.group(0)
        if "." in num or "," in num:
            return f"{num} {forms[2]}"
        n = int(num)
        return f"{pl_number(n)} {pl_plural(n, forms)}"

    def replace_currency_dec(m):
        whole, frac = int(m.group(1)), int(m.group(2))
        cur = m.group(3).lower()
        forms = CURRENCY.get(cur)
        if not forms:
            return m.group(0)
        base = f"{pl_number(whole)} {pl_plural(whole, forms)}"
        if frac == 0:
            return base
        cent = _CENT_FORMS.get(cur, ("grosz", "grosze", "groszy"))
        return f"{base} {pl_number(frac)} {pl_plural(frac, cent)}"

    def replace_count(m):
        n, word = int(m.group(1)), m.group(2)
        key = _FORM_TO_KEY.get(normalize_facts(word))
        if not key:
            return m.group(0)
        return f"{n} {pl_plural(n, COUNT_NOUNS[key])}"

    def replace_fraction(m):
        return FRACTIONS.get(f"{m.group(1)}/{m.group(2)}", m.group(0))

    def replace_temporal(m):
        n, word = int(m.group(1)), m.group(2)
        norm = normalize_facts(word)
        # Biernik lp żeński: „minutę/godzinę/sekundę" -> „jedną minutę" itd.
        if n == 1 and norm in ("minute", "godzine", "sekunde"):
            return f"jedną {word}"
        key = _FORM_TO_KEY.get(norm)
        if key not in TEMPORAL_KEYS:
            return m.group(0)
        return f"{_num_words(n, key in _FEMININE_KEYS)} {pl_plural(n, COUNT_NOUNS[key])}"

    def replace_ordinal(m):
        n, word = int(m.group(1)), m.group(2)
        forms = _ORDINAL_NOUNS.get(normalize_facts(word))
        if not forms or not 1 <= n <= 31:
            return m.group(0)
        return f"{forms[n]} {word}"

    def replace_case(m):
        n, word = int(m.group(1)), m.group(2)
        if not 2 <= n <= 10:
            return m.group(0)
        norm = normalize_facts(word)
        key = _CASE_FORM_TO_KEY.get(norm)
        if not key:
            return m.group(0)
        if norm.endswith("ami"):
            return f"{NUM_INSTR[n]} {CASE_FORMS[key][0]}"
        return f"{NUM_LOC[n]} {CASE_FORMS[key][1]}"

    def replace_month_loc(m):
        loc = _MONTH_LOC.get(normalize_facts(m.group(2)))
        return f"{m.group(1)} {loc}" if loc else m.group(0)

    def replace_range(m):
        a, b = int(m.group(1)), int(m.group(2))
        if 1 <= a <= 10 and 1 <= b <= 10:
            return f"od {_GEN[a]} do {_GEN[b]}"
        return m.group(0)

    def replace_do(m):
        n = int(m.group(1))
        return f"do {_GEN[n]}" if n in _GEN else m.group(0)

    def replace_century(m):
        n = int(m.group(1))
        if not 1 <= n <= 31:
            return m.group(0)
        base = _ORDINAL_M[n]
        if normalize_facts(m.group(2)).startswith("wieku"):
            base = _loc_masculine(base)
        return f"{base} {m.group(2)}"

    def replace_child(m):
        n = int(m.group(1))
        if not 1 <= n <= 10:
            return m.group(0)
        return f"{_COLLECT.get(n) or pl_number(n)} {'dziecko' if n == 1 else 'dzieci'}"

    def replace_half_unit(m):
        return f"{m.group(1)} {_UNIT_GEN.get(m.group(2), m.group(2))}"

    def replace_roman(m):
        n = roman_to_int(m.group(1))
        if not 1 <= n <= 39:
            return m.group(0)
        base = ordinal_m(n)
        if normalize_facts(m.group(2)).startswith("wieku"):
            base = _loc_masculine(base)
        return f"{base} {m.group(2)}"

    def replace_unit_word(m):
        n, unit = int(m.group(1)), m.group(2)
        if unit in _PER_SEC:
            forms, suffix, fem = _PER_SEC[unit]
            return f"{_num_words(n, fem)} {pl_plural(n, forms)} {suffix}"
        key = _unit_key(unit)
        forms = _UNIT_WORDS.get(key)
        if not forms:
            return m.group(0)
        return f"{_num_words(n, key in _FEMININE_UNITS)} {pl_plural(n, forms)}"

    def replace_percent(m):
        txt = m.group(1).replace(",", ".")
        whole = int(float(txt))
        out = pl_number(whole)
        frac = txt.partition(".")[2]
        if frac and int(frac):
            out += " przecinek " + frac_words(frac)
            return out + " procent"
        return out + " " + pl_plural(whole, ("procent", "procenty", "procent"))

    def replace_date_iso(m):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not 1 <= mo <= 12:
            return m.group(0)
        return f"{d} {PL_MONTHS_GEN[mo - 1]} {y}"

    def replace_date_eu(m):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not 1 <= mo <= 12:
            return m.group(0)
        return f"{d} {PL_MONTHS_GEN[mo - 1]} {y}"

    def replace_day_month(m):
        d = int(m.group(1))
        if not 1 <= d <= 31:
            return m.group(0)
        return f"{PL_DAYS_ORD_GEN[d]} {m.group(2)}"

    text = text.replace("\n", " ")
    text = _EMOJI_RE.sub(" ", text)
    text = _THOUSANDS_RE.sub("", text)
    text = _FRACTION_RE.sub(replace_fraction, text)
    text = _QUARTER_RE.sub("ćwierć", text)
    text = _HALF_RE.sub("pół", text)
    text = _HALF_UNIT_RE.sub(replace_half_unit, text)
    text = _CURRENCY_DEC_RE.sub(replace_currency_dec, text)
    text = _CURRENCY_RE.sub(replace_currency, text)
    text = re.sub(r"(?<![\w])-(\d+)", r"minus \1", text)
    for rx, repl in TTS_ABBREV:
        text = rx.sub(repl, text)
    for rx, repl in TTS_PRONOUNCE:
        text = rx.sub(repl, text)
    text = apply_lexicon(text)
    text = TTS_DATE_ISO.sub(replace_date_iso, text)
    text = TTS_DATE_EU.sub(replace_date_eu, text)
    text = PL_DAY_MONTH_RE.sub(replace_day_month, text)
    text = TTS_POSTAL_RE.sub(replace_postal, text)
    text = _UNIT_WORD_RE.sub(replace_unit_word, text)
    text = TTS_UNIT_RE.sub(replace_unit, text)
    text = TTS_O_GODZ_RE.sub(replace_oclock, text)
    text = TTS_GODZ_RE.sub(replace_godz, text)
    text = _O_DOT_RE.sub(replace_oclock, text)
    text = _GODZ_DOT_RE.sub(replace_godz, text)
    text = TTS_OCLOCK_RE.sub(replace_oclock, text)
    text = TTS_TIME_RE.sub(replace_time, text)
    text = TTS_PERCENT_RE.sub(replace_percent, text)
    text = TTS_DEC_RE.sub(replace_decimal, text)
    text = _ORDINAL_RE.sub(replace_ordinal, text)
    text = _CASE_RE.sub(replace_case, text)
    text = _W_LOC_RE.sub(replace_month_loc, text)
    text = _RANGE_RE.sub(replace_range, text)
    text = _CENTURY_RE.sub(replace_century, text)
    text = _ROMAN_RE.sub(replace_roman, text)
    text = _CHILD_RE.sub(replace_child, text)
    text = _DO_RE.sub(replace_do, text)
    text = re.sub(r"\b(\d+)\s+([A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+)\b", replace_temporal, text)
    text = re.sub(r"\b(\d+)\s+([A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+)\b", replace_count, text)
    for rx, repl in TTS_SYMBOLS:
        text = rx.sub(repl, text)
    text = _ensure_pauses(text)
    text = re.sub(r",(?=\S)", ", ", text)
    text = re.sub(r"\.(?=[A-ZĄĆĘŁŃÓŚŹŻ])", ". ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,.;:!?])\1+", r"\1", text)
    text = re.sub(r",\s*,+", ", ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def prepare_speech(text):
    """Pełna kosmetyka mowy (używana przez TTS i testy): markdown -> feminizacja -> wymowa."""
    return speakable(feminize(strip_markdown(text or "")))


__all__ = ["feminize", "strip_markdown", "speakable", "prepare_speech", "pl_number", "pl_plural",
           "ordinal_m", "roman_to_int"]
