"""Kosmetyka tekstu mowy (B5): feminizacja, czyszczenie markdownu i emoji.

Wydzielone z `audio/text.py` (monolit 800 linii) — spójny, samodzielny blok transformacji
tekstu, bez zależności od liczb/jednostek/dat. `audio/text.py` re-eksportuje te nazwy, więc
publiczne API (`audio.feminize`, `audio.strip_markdown`) się nie zmienia.
"""

import re

FEM_IRREG = (
    (re.compile(r"\bposzedłem\b", re.I), "poszłam"),
    (re.compile(r"\bprzyszedłem\b", re.I), "przyszłam"),
    (re.compile(r"\bprzeszedłem\b", re.I), "przeszłam"),
    (re.compile(r"\bwszedłem\b", re.I), "weszłam"),
    (re.compile(r"\bwyszedłem\b", re.I), "wyszłam"),
    (re.compile(r"\bodszedłem\b", re.I), "odeszłam"),
    (re.compile(r"\bzszedłem\b", re.I), "zszłam"),
    (re.compile(r"\bobszedłem\b", re.I), "obeszłam"),
    (re.compile(r"\bszedłem\b", re.I), "szłam"),
    (re.compile(r"\bposzedłbym\b", re.I), "poszłabym"),
    (re.compile(r"\bprzyszedłbym\b", re.I), "przyszłabym"),
    (re.compile(r"\b([Bb])ędę mógł\b"), r"\1ędę mogła"),
    (re.compile(r"\bmógłbym\b", re.I), "mogłabym"),
)
FEM_CONT_PAST = re.compile(r"\b(\w*?)ąłem\b")
FEM_CONT_COND = re.compile(r"\b(\w*?)ąłbym\b")
FEM_PAST = re.compile(r"\b(\w{2,})łem\b")
FEM_COND = re.compile(r"\b(\w{2,})łbym\b")
FEM_FUT = re.compile(r"\b([Bb]ędę\s+)(\w{2,})ł\b")
FEM_ADJ = re.compile(
    r"\b([Jj]estem\s+(?:bardzo\s+|dość\s+|trochę\s+|całkiem\s+|nadal\s+|już\s+)?\w+)y\b")
FEM_ADJ_BYLAM = re.compile(
    r"\b([Bb]yłam\s+(?:bardzo\s+|dość\s+|trochę\s+|całkiem\s+|już\s+)?\w+)y\b")
FEM_ADJ_CZUJE = re.compile(
    r"\b([Cc]zuj[ęe] się\s+(?:bardzo\s+|dość\s+|trochę\s+|całkiem\s+|jak\s+)?\w+)y\b")
FEM_SPECIAL = (
    (re.compile(r"\b([Jj])estem gotów\b"), r"\1estem gotowa"),
    (re.compile(r"\b([Jj])estem pewien\b"), r"\1estem pewna"),
    (re.compile(r"\b([Jj])estem sam\b"), r"\1estem sama"),
    (re.compile(r"\b([Jj])estem pełen\b"), r"\1estem pełna"),
    (re.compile(r"\b([Jj])estem zdrów\b"), r"\1estem zdrowa"),
    (re.compile(r"\b([Jj])estem winien\b"), r"\1estem winna"),
    (re.compile(r"\b([Jj])estem rad\b"), r"\1estem rada"),
    (re.compile(r"\b([Bb])y(?:łem|łam) gotów\b"), r"\1yłam gotowa"),
    (re.compile(r"\b([Bb])y(?:łem|łam) pewien\b"), r"\1yłam pewna"),
    (re.compile(r"\b([Bb])y(?:łem|łam) sam\b"), r"\1yłam sama"),
    (re.compile(r"\b([Bb])y(?:łem|łam) pełen\b"), r"\1yłam pełna"),
    (re.compile(r"\b([Bb])y(?:łem|łam) winien\b"), r"\1yłam winna"),
    (re.compile(r"\b([Bb])y(?:łem|łam) rad\b"), r"\1yłam rada"),
    (re.compile(r"\bpowinienem\b", re.I), "powinnam"),
    (re.compile(r"\bwinienem\b", re.I), "winnam"),
    (re.compile(r"\bto sam\b", re.I), "to sama"),
)

# Emoji, piktogramy i znaki techniczne — do usunięcia (nie czytamy ich).
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\u2190-\u21FF\u2300-\u23FF\u2B00-\u2BFF\uFE0F\u200d\u200b]")


def _case_repl(m, repl):
    s = m.expand(repl)
    if m.group(0)[:1].isupper() and s[:1].islower():
        s = s[:1].upper() + s[1:]
    return s


def feminize(text):
    if not text:
        return text
    t = text
    for rx, repl in FEM_IRREG:
        t = rx.sub(lambda m, r=repl: _case_repl(m, r), t)
    t = FEM_CONT_COND.sub(r"\1ęłabym", t)
    t = FEM_CONT_PAST.sub(r"\1ęłam", t)
    t = FEM_COND.sub(r"\1łabym", t)
    t = FEM_PAST.sub(r"\1łam", t)
    t = FEM_FUT.sub(r"\1\2ła", t)
    t = FEM_ADJ.sub(r"\1a", t)
    t = FEM_ADJ_BYLAM.sub(r"\1a", t)
    t = FEM_ADJ_CZUJE.sub(r"\1a", t)
    for rx, repl in FEM_SPECIAL:
        t = rx.sub(lambda m, r=repl: _case_repl(m, r), t)
    return t


def strip_markdown(text):
    if not text:
        return text
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    t = re.sub(r"(?<!\w)[*_`]+|[*_`]+(?!\w)", "", t)
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)
    t = re.sub(r"(?m)^\s*[-*]\s+", "", t)
    t = re.sub(r"\s#+\s", " ", t)
    t = re.sub(r"\[(.*?)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[ \t]+", " ", t).strip()
    return t


__all__ = ["feminize", "strip_markdown", "FEM_IRREG", "FEM_SPECIAL"]
