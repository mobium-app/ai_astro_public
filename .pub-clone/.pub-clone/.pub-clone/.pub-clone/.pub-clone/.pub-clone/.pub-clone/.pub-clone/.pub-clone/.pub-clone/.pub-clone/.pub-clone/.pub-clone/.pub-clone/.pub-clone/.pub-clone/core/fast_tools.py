"""Szybkie ścieżki deterministyczne (bez modelu) - tanie, pewne odpowiedzi.

Kolejność: potwierdzenia (w `dispatch`) -> zasilanie -> wiedza offline -> NPU -> zasoby.
Wiedza offline jest deterministyczna (fakty/pierwsza pomoc/`learned`), więc ASTRO odpowiada
bez udziału modelu na proste pytania (np. „co to jest podatek Belki").
"""

import re
import time

from ..memory import first_aid_reply, offline_facts_answer
from ..safety import classify_request, normalize_command, normalize_facts
from ..safety import verbs

INFO_RE = re.compile(
    r"temperatur|throttl|procesor|\bcpu\b|\bdysk\w*|miejsce|\bram\b|pami[eę]c|uptime|godzin|"
    r"czas\b|dat[ęa]|obci[aą]ż|zasob|\bsystem\w*")
NPU_RE = re.compile(r"hailo|\bnpu\b|telemetr|akcelerator")

# Czas/data odpowiadamy deterministycznie i ZWIĘŹLE (przed ogólnym system_info i przed
# ścieżką „question", która inaczej wysyła „jaka data" do modelu).
TIME_RE = re.compile(
    r"\b(?:ktora|jaka)\s+(?:jest\s+)?godzina\b|\bpodaj\s+(?:mi\s+)?(?:godzine|czas)\b|"
    r"\baktualna\s+godzina\b|\bktora\s+godzina\b|\bczas\s+teraz\b|^\s*godzina\s*[.!?]?\s*$")
DATE_RE = re.compile(
    r"\b(?:jaka|jaki|ktora|ktory)\s+(?:jest\s+|mamy\s+)?(?:dzisiaj\s+|dzis\s+)?(?:data|dzien)\b|"
    r"\bpodaj\s+(?:mi\s+)?(?:dzisiejsz\w*\s+)?date\b|"
    r"\bjak[ai]\s+(?:dzisiaj\s+)?dzien\b|"
    r"\bdzisiejsza\s+data\b|^\s*data\s*[.!]?\s*$")
# Tylko temperatura CPU (1:1 z plikiem must-have: bez dysku/RAM/uptime/daty).
# „ce pe u" = fonetyczny zapis CPU (Whisper/Vosk).
TEMP_RE = re.compile(r"\btemperatur\w*\s+(?:procesora|cpu|ce\s+pe\s+u|ce-pe-u)\b|\bcpu\b(?!\s*\w)")
# Gdy zdanie łączy temperaturę z innymi zasobami, wracamy do pełnego system_info.
_TEMP_OTHER_RE = re.compile(r"dysk|ram|pami[eę]|miejsce|uptime|zasob|obci[aą]|load")
_DAYS_PL = ("poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela")

# Zasilanie Raspberry Pi (wyłącznie z potwierdzeniem). Wzorce na tekście znormalizowanym
# (bez diakrytyków, ł->l). Wymagają słowa docelowego, by nie łapać „wyłącz usługę/wifi".
POWER_SHUTDOWN_RE = re.compile(
    r"\b(?:wylacz|zamknij|zgas|shutdown)\w*\s+"
    r"(?:system|komputer|urzadz\w*|malin\w*|raspberry|serwer|\bpi\b)"
    r"|\b(?:wylacz|zamknij)\s+sie\b")
POWER_REBOOT_RE = re.compile(
    r"(?:\b(?:restart|restaart|zrestartuj|restartuj|reset|resetuj|zresetuj|reboot)\w*\s*"
    r"(?:system|komputer|urzadz\w*|malin\w*|raspberry|serwer|\bpi\b))"
    r"|(?:uruchom\s+ponownie\s+(?:system|komputer|urzadz\w*|malin\w*|serwer|\bpi\b))"
    r"|\b(?:reset|resetuj|zresetuj)\w*\s+sie\b")
POWER_NEG_RE = re.compile(
    r"uslug|wifi|siec|firewall|aplikacj|program|proces|dokument|zabezpiecze|kart|okn|"
    r"myszk|monitor|usb")

# Komendy ZMIENIAJĄCE system: nie wolno ich odpowiadać przez fast-path system_info/npu
# (np. „zaktualizuj aplikacje systemowe" zawiera „system" i wcześniej zwracał temperaturę!).
# Definicja czasowników: `safety/verbs.py` (C7).
MUTATE_RE = verbs.mutate_re()

# Deterministyczna aktualizacja (jak w Atenie): repozytoria -> update, system/pakiety -> full.
_UPDATE_VERB_RE = re.compile(
    r"\b(?:zaktualizuj|uaktualnij|aktualizuj|odswiez|upgrade|update|updejt|updejtuj|"
    r"aktualizacj\w*)\w*")
_UPDATE_OBJ_RE = re.compile(
    r"repozytori|\bzrodl|\brepo\b|\bupdate\b|\bupdejt|\bapps?\b|pakiet|pakiety|system|aplikacj|"
    r"oprogramowan|program\w*|\bapt\b|dystrybucj|linux")
# „updejt repo / updejt apps" (fonetyczny skrót) — sam czasownik + obiekt repo/apps.
_UPDATE_SHORT_RE = re.compile(
    r"\b(?:updejt|update)\w*\s+(?:repo|apps?|repozytori\w*|aplikacj\w*|system\w*)\b")

# Zasoby jako drzewko (na terminal) oraz raport HTML do folderu udostępnionego.
RESOURCE_RE = re.compile(
    r"\b(?:drzewko|zasoby(?:\s+(?:systemu|lokalne))?|stan\s+zasob\w*|"
    r"wykorzystanie\s+(?:dysku|ram|pami[eę]ci|zasob\w*|procesora|cpu)|"
    r"poziom\s+wykorzystania|poka[zż]\s+zasoby)")
REPORT_RE = re.compile(
    r"\b(?:utw[oó]rz|zr[oó]b|wygeneruj|generuj|przygotuj|stworz|sporzadz)\s+raport\w*|"
    r"\braport\s+(?:post[eę]pu|progresu|zasob\w*|systemu|stanu)\b")

# Szybkie ścieżki dodatkowe (port z Ateny): status aktualizacji, głośność, usługa, pogoda.
UPDATE_STATUS_RE = re.compile(
    r"status\s+aktualizacj|czy\s+s[aą]\s+aktualizacj|sprawdz\s+aktualizacj|"
    r"dost[eę]pne\s+aktualizacj|ile\s+aktualizacj|aktualizacje\s+do\s+instalacj")
VOLUME_RE = re.compile(
    r"\b(?:glosnos\w*|poziom\s+(?:dzwieku|glosnosci)|jaki\s+d[zż]wiek|podglos\w*|przycisz\w*|"
    r"wycisz\w*|scisz\w*|glosniej|ciszej|ustaw\s+glosnos\w*)\b")
SERVICE_RE = re.compile(
    r"\b(?:stan|status)\s+(?:uslug\w*|samb\w*|smb\w*|ssh|astro|ollama|hailo|cron|nftables|"
    r"avahi|bluetooth)\b|\bczy\s+dziala\s+uslug\w*")
WEATHER_RE = re.compile(
    r"\b(?:pogoda|prognoza|temperatura\s+na\s+zewn[aą]trz|jaka\s+bedzie\s+pogoda)\b")
# PRZEWALUTOWANIE (must-have): „aktualny kurs dolara/euro" -> kurs NBP + przeliczenie na PLN.
CURRENCY_RE = re.compile(
    r"\b(?:kurs\w*|przelicz\w*|przeliczenie|ile\s+kosztuje|jaki\s+jest\s+kurs|wymian\w*)\b"
    r"[^.!?]*\b(?:dolar\w*|usd|euro|eur|funt\w*|gbp|frank\w*|chf|jen\w*|jpy|juan\w*|cny|yuan)\b")

# Pytania wymagające rozumowania/porównania zostają dla modelu (nie odpowiadamy faktem).
REASON_RE = re.compile(
    r"porown|roznic|dlaczego|policz|oblicz|wytlumacz krok|krok po kroku|z jednej strony|"
    r"lepsz|gorsz|wady|zalety")
# Teoria o pojęciach („co to jest system plików", „jak działa pamięć") NIE może trafić w
# fast-path INFO (który łapie słowa „system"/„pamięć") — ma iść do wiedzy/modelu.
THEORY_RE = re.compile(
    r"\b(co to jest|co to sa|czym jest|czym sa|czym sie rozni|wyjasnij|opowiedz|"
    r"jak dziala|jak dzila|do czego sluzy|do czego sluz|zdefiniuj|omow|porownaj)\b")

# Prosta matematyka (deterministycznie, bez modelu i bez chmury): "oblicz ile to jest 2 + 2".
# Obsługiwane: dodawanie, odejmowanie, mnożenie, dzielenie (+ nawiasy, ułamki). Tekst znormalizowany
# (bez diakrytyków, ł->l). NIE łapie zadań złożonych (całki, równania) - te idą do modelu.
MATH_TRIGGER_RE = re.compile(
    r"\b(?:oblicz|policz|przelicz|ile\s+to\s+jest|ile\s+to\s+bedzie|wynik\s+dzia[lł]ania)\b")
_MATH_NOISE_RE = re.compile(
    r"\b(?:oblicz|policz|przelicz|podaj|prosze|mi|ile|to|jest|bedzie|wynosi|wynik|dzialani\w*|"
    r"ro[wn]na\w*|sie|jak|jest|jest\?)\b")
# Operatory słowne (kolejność ma znaczenie: najpierw „podzielić przez", potem reszta).
_MATH_OPS = (
    (re.compile(r"\bpodzielic\s+przez\b|\bpodziel\s+przez\b|\bpodzielone\s+przez\b"), "/"),
    (re.compile(r"\bplus\b|\bdodac\b|\bdodaj\b|\bdoda[ćc]\b|\bdo\s+do\b"), "+"),
    (re.compile(r"\bminus\b|\bodjac\b|\bodejmij\b|\bodj[ąć]\b"), "-"),
    (re.compile(r"\brazy\b|\bpomno[zż]\w*\b|\bprzemno[zż]\w*\b|\bmnozon\w*\b"), "*"),
    (re.compile(r"\bpodziel\w*\b|\bprzez\b"), "/"),
)
# Słowa-liczebniki (znormalizowane: bez diakrytyków, ł->l) -> wartość. Proste działania mówione.
_NUM_UNITS = {"zero": 0, "jeden": 1, "jedna": 1, "jedno": 1, "dwa": 2, "dwie": 2, "trzy": 3,
              "cztery": 4, "piec": 5, "szesc": 6, "siedem": 7, "osiem": 8, "dziewiec": 9}
_NUM_TEENS = {"dziesiec": 10, "jedenascie": 11, "dwanascie": 12, "trzynascie": 13,
              "czternascie": 14, "pietnascie": 15, "szesnascie": 16, "siedemnascie": 17,
              "osiemnascie": 18, "dziewietnascie": 19}
_NUM_TENS = {"dwadziescia": 20, "trzydziesci": 30, "czterdziesci": 40, "piecdziesiat": 50,
             "szescdziesiat": 60, "siedemdziesiat": 70, "osiemdziesiat": 80,
             "dziewiecdziesiat": 90}
_NUM_HUNDREDS = {"sto": 100, "dwiescie": 200, "trzysta": 300, "czterysta": 400, "piecset": 500,
                 "szescset": 600, "siedemset": 700, "osiemset": 800, "dziewiecset": 900}
_NUM_THOUSANDS = {"tysiac": 1000, "tysiace": 1000, "tysiecy": 1000, "tys": 1000}


def _numwords_to_digits(s):
    """Zamienia polskie liczebniki na cyfry w ciągu znormalizowanym ('dwa dodać dwa' -> '2 + 2')."""
    out, cur = [], 0
    for tok in s.split():
        if tok in _NUM_UNITS:
            cur += _NUM_UNITS[tok]
        elif tok in _NUM_TEENS:
            cur += _NUM_TEENS[tok]
        elif tok in _NUM_TENS:
            cur += _NUM_TENS[tok]
        elif tok in _NUM_HUNDREDS:
            cur += _NUM_HUNDREDS[tok]
        elif tok in _NUM_THOUSANDS:
            cur = (cur or 1) * 1000
            out.append(str(cur))
            cur = 0
        else:
            if cur:
                out.append(str(cur))
                cur = 0
            out.append(tok)
    if cur:
        out.append(str(cur))
    return " ".join(out)


def _safe_calc(s):
    """Bezpieczny parser arytmetyczny (bez eval): + - * / ( ) oraz liczby. Zwraca float."""
    tokens = re.findall(r"\d+\.?\d*|[()+\-*/]", s)
    if not tokens:
        raise ValueError("brak wyrażenia")
    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def take():
        t = peek()
        pos[0] += 1
        return t

    def expr():
        v = term()
        while peek() in ("+", "-"):
            op = take()
            r = term()
            v = v + r if op == "+" else v - r
        return v

    def term():
        v = factor()
        while peek() in ("*", "/"):
            op = take()
            r = factor()
            if op == "*":
                v *= r
            else:
                if r == 0:
                    raise ZeroDivisionError
                v /= r
        return v

    def factor():
        t = take()
        if t == "(":
            v = expr()
            if take() != ")":
                raise ValueError("niedomknięty nawias")
            return v
        if t == "-":
            return -factor()
        if t == "+":
            return factor()
        return float(t)

    val = expr()
    if pos[0] != len(tokens):
        raise ValueError("reszta wyrażenia")
    return val


def _fmt_num(v):
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{round(v, 6):g}"


_OP_NAMES = (("+", "dodawania"), ("-", "odejmowania"), ("*", "mnożenia"), ("/", "dzielenia"))


def _op_name(s):
    names = [n for sym, n in _OP_NAMES if sym in s]
    return names[0] if len(names) == 1 else "działania"


def math_reply(text):
    """'oblicz ile to jest 2 + 2' -> 'Obliczam. Wynik dodawania to 4.' (1:1 z must-have).
    None, gdy to nie proste działanie."""
    low = normalize_facts(text or "")
    if not low or not MATH_TRIGGER_RE.search(low):
        return None
    s = low.replace(",", ".").replace("×", "*").replace("÷", "/")
    s = s.replace("**", "*")
    s = _numwords_to_digits(s)  # „dwa dodać dwa" -> „2 + 2"
    for rx, op in _MATH_OPS:
        s = rx.sub(f" {op} ", s)
    s = _MATH_NOISE_RE.sub(" ", s)
    s = re.sub(r"[^0-9+\-*/(). ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not re.search(r"\d", s) or not re.search(r"[+\-*/]", s):
        return None
    try:
        val = _safe_calc(s)
    except Exception:
        return None
    return f"Obliczam. Wynik {_op_name(s)} to {_fmt_num(val)}."



def _power(ctx, action):
    reg = getattr(ctx, "registry", None)
    if reg is None:
        return None
    return reg.execute("power", {"action": action}, ctx).text


def update_action(low):
    """'update' (repozytoria) | 'full' (system/pakiety) | None — gdy to nie aktualizacja."""
    if _UPDATE_SHORT_RE.search(low):
        # „updejt repo/updejt apps" — rozstrzyga obiekt: repo → update, apps/instaluj → full.
        if re.search(r"\brepo\b|repozytori|zrodl", low):
            return "update"
        return "full"
    if not (_UPDATE_VERB_RE.search(low) and _UPDATE_OBJ_RE.search(low)):
        return None
    if re.search(r"repozytori|zrodl", low) and not re.search(
            r"pakiet|system|aplikacj|oprogramowan|upgrade|full", low):
        return "update"
    return "full"


def _update(ctx, action):
    reg = getattr(ctx, "registry", None)
    if reg is None:
        return None
    return reg.execute("update_system", {"action": action}, ctx).text


def _resources():
    """Drzewko zasobów na terminal + krótkie podsumowanie do wypowiedzenia."""
    try:
        from .resources import human, resource_data, system_tree
    except Exception:
        return None
    tree = system_tree()
    try:
        from .. import mirror
        mirror.wall_write(tree)
    except Exception:
        pass
    d = resource_data()
    mi = d["mem"]
    parts = []
    temp = d["cpu"]["temp_c"]
    parts.append(f"CPU {temp} stopni" if temp is not None else "CPU w normie")
    parts.append(f"RAM {human(mi['used'])} z {human(mi['total'])}")
    root = next((x for x in d["disks"] if x["mount"] == "/"), None)
    if root and root["total"]:
        parts.append(f"dysk zajęty w {root['used'] / root['total'] * 100:.0f} procent")
    return "Zasoby: " + ", ".join(parts) + ". Drzewko pokazuję na terminalu."


def _report():
    try:
        from .. import report
        path = report.build_report()
        return f"Utworzyłam raport: {path}"
    except Exception as e:
        return f"Nie udało się utworzyć raportu: {e}"


# Kontynuacje rozmowy („a jak bardzo?", „i co dalej?", „a dlaczego?") — bez własnego tematu.
# Nie odpowiadamy ich z `learned` (RAG wziąłby przypadkowy ogólnik i zgubił kontekst), tylko
# puszczamy do agenta, który widzi pamięć roboczą sesji (P1). Tylko KRÓTKIE, spójnikowe starty.
FOLLOWUP_LEAD = frozenset({"a", "i", "ale", "wiec", "to", "no", "oraz", "potem", "nastepnie"})


def is_followup(text):
    """True dla krótkiej kontynuacji bez tematu (spójnik na starcie, <= 4 tokeny)."""
    low = normalize_facts(text or "")
    tokens = re.findall(r"[a-z0-9]+", low)
    if not tokens or tokens[0] not in FOLLOWUP_LEAD:
        return False
    return len(tokens) <= 4


def offline_knowledge(text, memory=None):
    """Deterministyczna odpowiedź z wiedzy offline albo None. Bez modelu."""
    low = normalize_facts(text or "")
    if not low or REASON_RE.search(low):
        return None
    try:
        ans = offline_facts_answer(text)
    except Exception:
        ans = None
    if ans:
        return ans
    try:
        ans = first_aid_reply(text)
    except Exception:
        ans = None
    if ans:
        return ans
    if memory is not None:
        try:
            ans = memory.best_learned(text)
        except Exception:
            ans = None
        if ans:
            return ans
    return None


def _time_date(low):
    """Krótka, deterministyczna odpowiedź o godzinie/dacie (albo None)."""
    if TIME_RE.search(low):
        return time.strftime("Jest godzina %H:%M.")
    if DATE_RE.search(low):
        wd = _DAYS_PL[time.localtime().tm_wday]
        return time.strftime(f"Dzisiaj jest {wd}, %d.%m.%Y.")
    return None


def _temperature():
    """Tylko temperatura CPU (plik must-have: „a nie kurwa cała regułka z data i godziną")."""
    try:
        from .resources import resource_data
        temp = resource_data()["cpu"]["temp_c"]
    except Exception:
        return None
    if temp is None:
        return "Nie mogę odczytać temperatury procesora."
    return f"Temperatura procesora wynosi {temp} stopni Celsjusza."


def try_fast(text, ctx):
    low = normalize_command(text or "")
    ans = _time_date(low)
    if ans:
        return ans
    math = math_reply(text)
    if math:
        return math
    if TEMP_RE.search(low) and not _TEMP_OTHER_RE.search(low):
        out = _temperature()
        if out:
            return out
    if REPORT_RE.search(low):        return _report()
    if RESOURCE_RE.search(low):
        out = _resources()
        if out:
            return out
    if UPDATE_STATUS_RE.search(low):
        from .extras import update_status_text
        return update_status_text()
    if WEATHER_RE.search(low):
        from .extras import weather_text
        mem = getattr(ctx, "memory", None)
        store = getattr(mem, "profiles", None) if mem is not None else None
        city = (store.get() or {}).get("city", "") if store is not None else ""
        return weather_text(text, fallback_city=city)
    if CURRENCY_RE.search(low):
        from .extras import currency_text
        out = currency_text(text)
        if out:
            return out
    if VOLUME_RE.search(low):
        from .extras import volume_text
        return volume_text(low)
    if SERVICE_RE.search(low):
        from .extras import service_name, service_status_text
        return service_status_text(service_name(text))
    action = update_action(low)
    if action:
        out = _update(ctx, action)
        if out:
            return out
    if not POWER_NEG_RE.search(low):
        if POWER_SHUTDOWN_RE.search(low):
            out = _power(ctx, "shutdown")
            if out:
                return out
        if POWER_REBOOT_RE.search(low):
            out = _power(ctx, "reboot")
            if out:
                return out
    mutating = bool(MUTATE_RE.search(low))
    theory = bool(THEORY_RE.search(low))
    reg = getattr(ctx, "registry", None)
    if not mutating and not theory and reg is not None:
        if NPU_RE.search(low):
            result = reg.execute("npu_status", {}, ctx)
            if result.ok:
                return result.text
        if INFO_RE.search(low):
            result = reg.execute("system_info", {}, ctx)
            if result.ok:
                return result.text
    if classify_request(text) == "question" and not is_followup(text):
        return offline_knowledge(text, getattr(ctx, "memory", None))
    return None
