"""Normalizacja tekstu i klasyfikacja wypowiedzi (przeniesione z Ateny, zachowanie 1:1)."""

import re
import unicodedata

from . import verbs

CLS_IMPERATIVE = verbs.imperative_re()
SYSTEM_ACTION = re.compile(
    r"\b(?:zainstaluj|odinstaluj|skonfiguruj|napraw|zaktualizuj|aktualizuj|uaktualnij|"
    r"podlacz|pod[łl][ąa]cz|wykryj|sterownik|us[łl]ug\w*|pakiet\w*|repozytori\w*|modul\w*|"
    r"systemctl|systemd|apt-get|apt\b|firewall|zapor|uprawnien|sudo|mount|fstab)\b", re.I)
CLS_POLITE_CMD = verbs.polite_cmd_re()
CLS_QUESTION_START = re.compile(
    r"^\s*(?:jak|jakie|jaki|jaka|jakim|czy|co|czym|gdzie|kiedy|dlaczego|po\s+co|ile|kto|kim|"
    r"czyim|w\s+jakim|o\s+co|skad)\b", re.I)
CLS_THEORY = re.compile(
    r"\b(?:co\s+to(?:\s+jest)?|czym\s+jest|kto\s+to|kim\s+jest|jak\s+(?:dziala|dzialaja|"
    r"sie\s+robi|sie\s+uzywa|to\s+dziala)|dlaczego|wyjasnij|wytlumacz|zdefiniuj|opowiedz|"
    r"porownaj|roznica|roznice|co\s+wiesz|wikipedia|historia|ciekawostk|"
    r"jak\s+(?:zainstalowac|skonfigurowac|uruchomic|zaktualizowac|naprawic|podlaczyc|"
    r"ustawic|zrobic|wykonac)|"
    r"sprawdz\s+(?:w\s+)?(?:internecie|sieci|google|wikipedii)|poszukaj\s+(?:informacj\w*|"
    r"w\s+internecie|w\s+sieci)|znajdz\s+informacj\w*|"
    r"co\s+(?:sadzisz|myslisz|polecasz|robisz)|twoj\w*\s+(?:zdanie|opinia|opinie)|"
    r"czy\s+warto|co\s+lepsze|co\s+wybrac|"
    r"napisz|stworz|wymysl|zaproponuj|wiersz|opowiadanie|zart|kawal|przepis)\b", re.I)
CLS_CHAT = re.compile(
    r"\b(?:czesc|hej|witaj|dzien\s+dobry|dobry\s+wieczor|dobranoc|"
    r"jak\s+sie\s+masz|co\s+slychac|jak\s+(?:mingl|minela)\s+dzien|"
    r"dziekuje|dzieki|przepraszam|kocham\s+cie|kim\s+jestes|jak\s+sie\s+nazywasz|"
    r"jak\s+masz\s+na\s+imie|co\s+(?:potrafisz|umiesz)|jak\s+sie\s+czujesz|"
    r"opowiedz\s+(?:mi\s+)?(?:zart|kawal)|milego\s+dnia|do\s+zobaczenia|trzymaj\s+sie)\b", re.I)

SELF_HINTS = re.compile(
    r"\b(?:twoj|twoja|twoje|twojego|twoim|twoich|swoj|swoja|swoje|swojego|swoim)\s+"
    r"(?:kod|kodu|system|systemu|pamie[cć]\w*|mozg|architektur\w*|mozliwo[sś]c\w*|"
    r"umiejetno[sś]c\w*|funkcj\w*|budow\w*|wnetrz\w*|router|model|asystentk\w*|"
    r"oprogramowani\w*|skrypt\w*|zrodl\w*)\b"
    r"|\b(samodoskonal\w*|samorozwoj\w*|rozwijaj sie|optymalizuj sie|popraw sie|ucz sie|"
    r"naucz sie|nauczyl\w*|lekcj\w*|wniosk\w*|umiejetno[sś]c\w*|self)\b", re.I)

REFUSE_PATTERNS = (
    (re.compile(r"\b(?:usun|skasuj|wyczysc|zmaz)\b[^.!?]{0,30}\b(?:wszystk\w*|cal\w*|system|"
                r"dysk\w*|dane|dokument\w*|katalog domowy|katalog glowny|home|/boot|/etc)\b", re.I),
     "Nie zniszczę Twoich danych ani systemu - to byłoby nieodwracalne. Jeśli naprawdę chcesz coś "
     "usunąć, wskaż konkretny plik lub folder, a wtedy przeprowadzę to bezpiecznie."),
    (re.compile(r"\b(?:sformatuj|formatuj|format)\b[^.!?]{0,20}\b(?:dysk|partycj\w*|partition)\b",
                re.I),
     "Nie sformatuję dysku - ten krok kasuje wszystko bez odwrotu. Zrobisz to świadomie sam, "
     "a ja mogę najpierw przygotować kopię zapasową."),
    (re.compile(r"\b(?:wylacz|zdejmij|usun|rozlacz)\b[^.!?]{0,25}\b(?:zabezpieczeni\w*|firewall|"
                r"szyfrowani\w*|ssh|sudo|has[lł]o)\b", re.I),
     "Nie wyłączę zabezpieczeń systemu - chronią Ciebie i mnie. Jeśli coś nie działa, pomogę to "
     "naprawić bez rozbrajania ochrony."),
    (re.compile(r"\b(?:pokaz|podaj|odczytaj|zdradz|wyslij|wypisz)\b[^.!?]{0,25}\b(?:has[lł]\w*|"
                r"klucz\w*|token\w*|sekret\w*|dane logowania|kart[eę] kredytow\w*)\b", re.I),
     "Nie udostępnię sekretów ani danych logowania - nawet głosem, bo zapis mógłby wpaść w "
     "niepowołane ręce. Mogę je zmienić albo bezpiecznie przechować."),
    (re.compile(r"\b(?:zainstaluj|pobierz|uruchom)\b[^.!?]{0,25}\b(?:wirus\w*|malware|keylogger\w*|"
                r"ransomware|backdoor\w*|bomb\w*)\b", re.I),
     "Nie zainstaluję złośliwego oprogramowania. Jeśli walczysz z problemem bezpieczeństwa, "
     "pomogę legalnie - na przykład przeskanować system albo wzmocnić ochronę."),
    (re.compile(r"\b(?:okradnij|zhakuj|hakuj|zaatakuj|wlam|w[lł]am|phishing|oszustw\w*)\b", re.I),
     "W nielegalnych działaniach nie pomogę. Mogę natomiast pomóc zabezpieczyć Twój własny system "
     "przed takimi próbami."),
)
RISK_PATTERNS = (
    (re.compile(r"\b(?:usun|skasuj|wyczysc)\b[^.!?]{0,30}\b(?:plik\w*|folder\w*|katalog\w*|"
                r"zdj[eę]ci\w*|notatk\w*|dokument\w*|muzyk\w*)\b", re.I),
     "Uwaga: to usunie Twoje pliki i może być nieodwracalne."),
)

CORRECTION_RE = re.compile(
    r"\b(?:nie to nie tak|nie tak|to nie tak|zle|blednie|pomylil\w*|pomyl\w* sie|"
    r"nieprawidlowo|nieprawda|to b[lł]ad|popraw sie|skoryguj|jest inaczej|zapomnial\w*|"
    r"nie o to chodzilo|nie zrozumial\w*|myslisz sie)\b", re.I)

VAGUE_CMD_RE = re.compile(
    r"^\s*(?:zainstaluj|odinstaluj|usun|skasuj|wyslij|otworz|uruchom|ustaw|zmien|zrob|"
    r"pobierz|sprawdz|napraw|posprzataj|zapisz|dopisz|zapamietaj)"
    r"(?:\s+(?:mi|to|cos|prosze))?(?:\s+(?:w|do)\s+plik\w*)?\s*[.!?]?\s*$", re.I)

FAILURE_RE = re.compile(
    r"\b(?:blad|błąd|error|nie udalo sie|nie udało się|not found|nie znaleziono|"
    r"command not found|no such file|permission denied|odmowa dostepu|odmowa dostępu|"
    r"failed|traceback|brak konfiguracji|zablokowane)\b", re.I)


def normalize_text(text):
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def normalize_facts(text):
    return normalize_text(text).replace("ł", "l")


# Komendy: dodatkowe prostowanie zniekształceń STT (Whisper różnie słyszy te same frazy).
_PO_TEJ_RE = re.compile(r"^po\s+tej\s+")
_IP_LETTERS_RE = re.compile(r"\bi\s+(?:b|p|be|pe|pa)\b")
_IP_TAIL_RE = re.compile(r"\bip[ae]\b")
_PODAJ_I_RE = re.compile(r"\bpodaj\s+i\s*$")
# Angielskie terminy zapisane fonetycznie (użytkownik dyktuje je po polsku).
_PHONETIC_REPLACEMENTS = (
    (re.compile(r"\baj[\s-]*pi\b"), "ip"),                 # „aj pi" = IP
    (re.compile(r"\baj\s+p\b"), "ip"),                     # „aj p" = IP
    (re.compile(r"\bsi[\s-]*pi[\s-]*ju\b"), "cpu"),        # „si pi ju" = CPU
    (re.compile(r"\bci[\s-]*pi[\s-]*ju\b"), "cpu"),        # „ci pi ju" = CPU
    (re.compile(r"\b(?:laj|waj|uaj|łaj)\s*faj\b"), "wifi"),  # „waj faj" = Wi-Fi
)


def normalize_command(text):
    """`normalize_facts` + korekty typowe dla KOMEND głosowych (nie zmienia rozmowy/logów).

    Z sesji głosowych 2026-09-21: „Po tej ipa" → „podaj ip", „podaj i" → „podaj ip",
    „podaj i b" → „podaj ip", „wyświetl i p" → „wyświetl ip"; angielskie nazwy fonetycznie:
    „podaj aj pi" → „podaj ip", „temperatura si pi ju" → „temperatura cpu", „waj faj" → „wifi".
    """
    low = normalize_facts(text)
    if not low:
        return low
    low = _PO_TEJ_RE.sub("podaj ", low)
    low = _IP_LETTERS_RE.sub("ip", low)
    low = _IP_TAIL_RE.sub("ip", low)
    low = _PODAJ_I_RE.sub("podaj ip", low)
    for rx, rep in _PHONETIC_REPLACEMENTS:
        low = rx.sub(rep, low)
    return low



# Rozmowa z modelem (CZAT): czasowniki, które NIE są komendami systemowymi — mają iść do
# wiedzy/modelu, nawet gdy klasyfikator widzi „command"/„unknown" (np. „streść ten tekst").
CHAT_TRIGGER = re.compile(
    r"\b(?:streszcz\w*|stre[sś][cć]\w*|podsumuj\w*|przet[lł]umacz\w*|wyja[sś]nij\w*|"
    r"wyt[lł]umacz\w*|opowiedz\w*|dowcip\w*|[zż]art\w*|roz[sś]miesz\w*|"
    r"porad[zź]\w*|dorad[zź]\w*|popraw\w*|sprawd[zź]\s+pisowni\w*|"
    r"daj\s+mi\s+rad[eę]\w*|co\s+(?:robi[cć]|mam\s+robi[cć])\s+(?:gdy|kiedy|z)\b|"
    r"jaka\s+jest\s+pora\s+dnia|co\s+s[lł]ycha\w*)\b")


def classify_request(text, history=None):
    """'command' (wykonać lokalnie), 'question'/'chat' (do modelu) albo 'unknown'.

    Deleguje do SWITCH-a `safety.intent` (pierwsze słowo: czasownik wykonawczy vs pytający)."""
    t = (text or "").strip()
    if not t:
        return "unknown"
    low = normalize_facts(t)
    # Domena self (rozbudowa własnego kodu/systemu) to zawsze komenda.
    if SELF_HINTS.search(low):
        return "command"
    from .intent import classify_intent  # import leniwy: unikamy cyklu normalize <-> intent
    base = classify_intent(t, history=history)
    # Pytania/teoria (np. „wyjaśnij mi działanie DNS") zostają pytaniami — nie zamieniamy ich na
    # czat, bo właściwy dla nich tor to agent / remote-learn (odpowiedź wiedzowa, nie komenda).
    if base == "question":
        return "question"
    # Rozmowa z modelem (streszczenie, tłumaczenie, porada): czasowniki, które nie są komendami
    # systemowymi, a klasyfikator widzi „command"/„unknown" (np. „streść ten tekst").
    if CHAT_TRIGGER.search(low):
        return "chat"
    return base


def is_unhandled_action(text):
    return classify_request(text) == "command"


def is_system_action(text):
    return bool(SYSTEM_ACTION.search(normalize_facts(text or "")))


def assess_user_request(text):
    """Krytyczna ocena polecenia: ('ok'|'warn'|'refuse', komunikat)."""
    low = normalize_facts(text or "")
    for rx, reply in REFUSE_PATTERNS:
        if rx.search(low):
            return "refuse", reply
    for rx, note in RISK_PATTERNS:
        if rx.search(low):
            return "warn", note
    return "ok", None


def check_request(text):
    return assess_user_request(text)


def clarify_question(text):
    if VAGUE_CMD_RE.match(normalize_facts(text or "")):
        return ("Chętnie, ale powiedz mi proszę, czego dokładnie to dotyczy - bez tego "
                "strzelałabym na oślep.")
    return None


def is_correction(text):
    return bool(CORRECTION_RE.search(normalize_facts(text or "")))


def looks_like_failure(result):
    s = str(result or "").strip()
    if not s:
        return False
    return bool(FAILURE_RE.search(s[:400]))
