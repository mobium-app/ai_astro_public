"""Skróty, wymowa i symbole + pauzy (B5) — wydzielone z `audio/text.py`, 1:1."""

import re

TTS_ABBREV = (
    (re.compile(r"\bm\.in\.", re.I), "między innymi"),
    (re.compile(r"\bprof\.", re.I), "profesor"),
    (re.compile(r"\bnp\.", re.I), "na przykład"),
    (re.compile(r"\bitd\.", re.I), "i tak dalej"),
    (re.compile(r"\bitp\.", re.I), "i tym podobne"),
    (re.compile(r"\btzn\.", re.I), "to znaczy"),
    (re.compile(r"\btj\.", re.I), "to jest"),
    (re.compile(r"\bśw\.", re.I), "święty"),
    (re.compile(r"\bdr hab\.", re.I), "doktor habilitowany"),
    (re.compile(r"\bdr\b", re.I), "doktor"),
    (re.compile(r"\bmgr\b", re.I), "magister"),
    (re.compile(r"\bnr\b", re.I), "numer"),
    (re.compile(r"\bstr\.", re.I), "strona"),
    (re.compile(r"\bust\.", re.I), "ustęp"),
    (re.compile(r"\bart\.", re.I), "artykuł"),
    (re.compile(r"\btel\.", re.I), "telefon"),
    (re.compile(r"\bgodz\.", re.I), "godzina"),
    (re.compile(r"\br\.", re.I), "roku"),
    (re.compile(r"\btys\.", re.I), "tysięcy"),
    (re.compile(r"\btys\b", re.I), "tysięcy"),
    (re.compile(r"\bmln\b", re.I), "milionów"),
    (re.compile(r"\bgr\b", re.I), "groszy"),
    (re.compile(r"\bproc\.", re.I), "procent"),
    (re.compile(r"\btzw\.", re.I), "tak zwany"),
    (re.compile(r"\bwoj\.", re.I), "województwo"),
    (re.compile(r"\bwg\.", re.I), "według"),
    (re.compile(r"\bmld\b", re.I), "miliardów"),
    (re.compile(r"\binż\.", re.I), "inżynier"),
    (re.compile(r"\blek\.", re.I), "lekarz"),
    (re.compile(r"\bgen\.", re.I), "generał"),
    (re.compile(r"\bpłk\b", re.I), "pułkownik"),
    (re.compile(r"\bmjr\b", re.I), "major"),
    (re.compile(r"\bks\.", re.I), "ksiądz"),
    (re.compile(r"\bfax\b", re.I), "faks"),
    (re.compile(r"\bpon\.", re.I), "poniedziałek"),
    (re.compile(r"\bwt\.", re.I), "wtorek"),
    (re.compile(r"\bśr\.", re.I), "środa"),
    (re.compile(r"\bczw\.", re.I), "czwartek"),
    (re.compile(r"\bpt\.", re.I), "piątek"),
    (re.compile(r"\bsob\.", re.I), "sobota"),
    (re.compile(r"\bniedz\.", re.I), "niedziela"),
    (re.compile(r"\bzł\b", re.I), "złotych"),
    (re.compile(r"\bPLN\b"), "złotych"),
    (re.compile(r"\bUSD\b"), "dolarów"),
    (re.compile(r"\bEUR\b"), "euro"),
    (re.compile(r"\bGBP\b"), "funtów"),
    (re.compile(r"\bCHF\b"), "franków"),
    (re.compile(r"\bCZK\b"), "koron"),
    (re.compile(r"\bul\.", re.I), "ulicy"),
    (re.compile(r"\bal\.", re.I), "alei"),
    (re.compile(r"\bpl\.", re.I), "placu"),
    (re.compile(r"\bos\.", re.I), "osiedlu"),
    (re.compile(r"\bwww\.", re.I), " "),
)
TTS_PRONOUNCE = (
    (re.compile(r"\bOK\b"), "okej"),
    (re.compile(r"\be-?mail\b", re.I), "imejl"),
    (re.compile(r"\bonline\b", re.I), "onlajn"),
    (re.compile(r"\boffline\b", re.I), "oflajn"),
    (re.compile(r"\brouter\b", re.I), "ruter"),
    (re.compile(r"\bchat\b", re.I), "czat"),
    (re.compile(r"\bfeedback\b", re.I), "fidbek"),
    (re.compile(r"\bdeadline\b", re.I), "dedlajn"),
    (re.compile(r"\bupdate\b", re.I), "apdejt"),
    (re.compile(r"\bYouTube\b", re.I), "Jutub"),
    (re.compile(r"\bGoogle\b", re.I), "Gugl"),
    (re.compile(r"\bWindows\b", re.I), "Łindołs"),
    (re.compile(r"\bLinux\b", re.I), "Linuks"),
    (re.compile(r"\bPython\b", re.I), "Pajton"),
    (re.compile(r"\bWi-?Fi\b", re.I), "waj-faj"),
    (re.compile(r"\bSMS\b"), "esemes"),
)
TTS_SYMBOLS = (
    (re.compile(r"°C"), " stopni Celsjusza "),
    (re.compile(r"°F"), " stopni Fahrenheita "),
    (re.compile(r"°"), " stopni "),
    (re.compile(r"½"), " pół "),
    (re.compile(r"¼"), " ćwierć "),
    (re.compile(r"¾"), " trzy czwarte "),
    (re.compile(r"\b24/7\b"), " całodobowo "),
    (re.compile(r"https?://"), " "),
    (re.compile(r"#\s*(\d+)"), r"numer \1"),
    (re.compile(r"€"), " euro "),
    (re.compile(r"[$]"), " dolarów "),
    (re.compile(r"->|→"), " "),
    (re.compile(r"[—–]"), ", "),
    (re.compile(r"×"), " razy "),
    (re.compile(r"÷"), " podzielić przez "),
    (re.compile(r"≈"), " około "),
    (re.compile(r"±"), " plus minus "),
    (re.compile(r"\("), ", "),
    (re.compile(r"\)"), " "),
    (re.compile(r"…"), " "),
    # Znaki i symbole tylko oddzielamy spacją — NIE czytamy ich nazw
    # (koniec z „kratka", „małpa", „ukośnik", „daszek", „pionowa kreska").
    (re.compile(r"[#*_`\"„”«»\[\]{}()<>|~^=\\+/\\\\@&]"), " "),
)
# Spójniki przeciwstawiające: przecinek daje pauzę w mowie (Piper respektuje interpunkcję).
_PAUSE_CONJ_RE = re.compile(r"(?<=[0-9a-ząćęłńóśźżA-ZĄĆĘŁŃÓŚŹŻ])\s+(ale|jednak|natomiast|zatem)\b")
_PAUSE_INTRO_RE = re.compile(r"^(\s*)(Uwaga|Słuchaj)\s+(?=[0-9a-ząćęłńóśźżA-ZĄĆĘŁŃÓŚŹŻ])")


def _ensure_pauses(text):
    """Konserwatywne pauzy: przecinek przed spójnikiem przeciwstawiającym i po okrzyku."""
    if not text:
        return text
    text = _PAUSE_CONJ_RE.sub(r", \1", text)
    text = _PAUSE_INTRO_RE.sub(r"\1\2, ", text)
    return text
