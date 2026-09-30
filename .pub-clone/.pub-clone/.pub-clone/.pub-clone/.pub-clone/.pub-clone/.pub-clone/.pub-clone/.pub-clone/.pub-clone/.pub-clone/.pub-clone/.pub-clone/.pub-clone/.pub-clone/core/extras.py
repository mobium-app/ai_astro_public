"""Szybkie ścieżki deterministyczne: status aktualizacji, głośność, status usługi, pogoda.

Wszystko bez modelu (szybko i pewnie). Port wybranych intencji Ateny, których brakowało ASTRO.
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request

from .. import config, mirror
from ..safety import normalize_facts
from ..user import stt_fix

_CARD = "wm8960"
_UA = {"User-Agent": "ASTRO/1.0 (Raspberry Pi)"}

SERVICE_ALIASES = {
    "samba": "smbd", "smb": "smbd", "nmbd": "nmbd", "ssh": "ssh", "sshd": "ssh",
    "astro": "astro", "ollama": "ollama", "hailo": "hailo-ollama", "cron": "cron",
    "nftables": "nftables", "avahi": "avahi-daemon", "bluetooth": "bluetooth",
}


def _run(argv, timeout=20):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:
        return 1, str(e)


# --- aktualizacje: status ---------------------------------------------------------------
def update_status_text():
    code, out = _run(["apt-get", "-s", "-q", "upgrade"], timeout=120)
    count = len(re.findall(r"^Inst\s", out, re.M))
    if code != 0 and not out:
        return "Nie udało się sprawdzić aktualizacji."
    if count == 0:
        return "System jest aktualny — brak pakietów do aktualizacji."
    sample = re.findall(r"^Inst\s+(\S+)", out, re.M)[:6]
    hist = ""
    try:
        with open("/var/log/apt/history.log", encoding="utf-8", errors="replace") as fh:
            tail = fh.read()[-2000:]
        m = re.findall(r"Start-Date: ([^\n]+)", tail)
        if m:
            hist = f" Ostatnia aktualizacja: {m[-1]}."
    except OSError:
        pass
    return (f"Dostępnych aktualizacji: {count} (np. {', '.join(sample)})."
            f" Powiedz „zaktualizuj system”, aby je zainstalować.{hist}")


# --- głośność ---------------------------------------------------------------------------
_VOL_RE = re.compile(r"\[(\d+)%\]")


def volume_get():
    code, out = _run(["amixer", "-D", f"hw:CARD={_CARD}", "sget", "Playback"])
    m = _VOL_RE.search(out)
    if code != 0 or not m:
        return None
    return int(m.group(1))


def volume_set(percent):
    percent = max(0, min(100, int(percent)))
    val = int(round(percent / 100 * 255))
    mirror.command(f"amixer -D hw:CARD={_CARD} sset Playback {val}", root=False)
    code, out = _run(["amixer", "-D", f"hw:CARD={_CARD}", "sset", "Playback", str(val)])
    mirror.command(f"amixer ... Playback {val}", out[:300], code)
    return code == 0


def volume_text(low):
    cur = volume_get()
    if cur is None:
        return "Nie mogę odczytać głośności (karta WM8960 niedostępna)."
    if re.search(r"wycisz|mute|scisz do zera", low):
        volume_set(0)
        return "Wyciszyłam dźwięk."
    m = re.search(r"(\d{1,3})\s*(?:%|procent)", low)
    if m:
        target = int(m.group(1))
        volume_set(target)
        return f"Ustawiłam głośność na {target} procent."
    if re.search(r"maks|na ful|maximum", low):
        volume_set(100)
        return "Ustawiłam głośność na maksimum."
    # must-have: skok o 20% za każdym razem; wzrost do maks. 100%, spadek do min. 20%.
    if re.search(r"podglosn|glosniej|zwieksz|podglosc", low):
        target = min(100, cur + 20)
        volume_set(target)
        return f"Głośniej. Głośność {target} procent."
    if re.search(r"przycisz|ciszej|zmniejsz|scisz", low):
        target = max(20, cur - 20)
        volume_set(target)
        return f"Ciszej. Głośność {target} procent."
    return f"Głośność wynosi {cur} procent."


# --- usługi -----------------------------------------------------------------------------
def service_name(text):
    low = normalize_facts(text)
    m = re.search(r"uslug\w*\s+([a-z0-9_.-]+)", low)
    if m:
        name = m.group(1)
    else:
        name = next((a for a in SERVICE_ALIASES
                     if a in low or (len(a) > 3 and a[:-1] in low)), "")
    name = SERVICE_ALIASES.get(name, name)
    return name if name and re.match(r"^[a-z0-9_.@-]+$", name) else ""


def service_status_text(name):
    if not name:
        return "Nie rozpoznałam nazwy usługi."
    if not shutil.which("systemctl"):
        return "Brak systemctl."
    code, out = _run(["systemctl", "is-active", name])
    active = out.strip()
    if active in ("active", "activating"):
        code2, out2 = _run(["systemctl", "status", name, "--no-pager", "-n", "3"])
        return f"Usługa {name}: działa ({active}).\n{out2[:600]}"
    if active in ("inactive", "failed", "deactivating"):
        return f"Usługa {name}: {active}."
    if code != 0 and not active:
        return f"Nie znalazłam usługi {name}."
    return f"Usługa {name}: {active}."


# --- pogoda (Open-Meteo, bez klucza) ----------------------------------------------------
_WMO = {0: "bezchmurnie", 1: "prawie bezchmurnie", 2: "częściowe zachmurzenie",
        3: "zachmurzenie", 45: "mgła", 48: "mgła osadzająca", 51: "lekka mżawka",
        53: "mżawka", 55: "mocna mżawka", 61: "lekki deszcz", 63: "deszcz", 65: "ulewa",
        71: "lekki śnieg", 73: "śnieg", 75: "duży śnieg", 80: "przelotny deszcz",
        81: "przelotne opady", 82: "gwałtowne opady", 95: "burza", 96: "burza z gradem"}


def _get_json(url):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


_CITY_STOP = {"w", "we", "dla", "na", "o", "jaka", "jaki", "jakie", "jest", "bedzie", "dzis",
              "dzisiaj", "jutro", "pojutrze", "podaj", "sprawdz", "pokaz", "prosze", "mi",
              "temperatura", "stopni", "stopnie", "jaka", "czy", "no"}


def extract_city(text):
    """Miasto z wypowiedzi o pogodzie; odporne na szyk „jaka pogoda w X" i bez przyimka."""
    low = normalize_facts(text)
    if not low:
        return ""
    toks = [t for t in re.split(r"[^a-z0-9\-]+", low) if t]
    content = [t for t in toks
               if t not in _CITY_STOP and not t.startswith(("pogod", "prognoz", "temperatur"))]
    if not content:
        return ""
    city = content[-1]
    if len(city) < 3 and len(content) >= 2:
        city = " ".join(content[-2:])
    return city.strip("?.!-")


# Aliasy dużych miast PL: geokoder open-meteo wymaga diakrytyków dla części nazw
# („lodz"/„wroclaw" nie znajdują miasta), a STT podaje formy odmienione.
_CITY_ALIASES = {
    "warszawa": "Warszawa", "warszawie": "Warszawa", "warszawy": "Warszawa",
    "krakow": "Kraków", "krakowie": "Kraków", "krakowa": "Kraków",
    "lodz": "Łódź", "lodzi": "Łódź", "lodzia": "Łódź",
    "wroclaw": "Wrocław", "wroclawiu": "Wrocław", "wroclawia": "Wrocław",
    "poznan": "Poznań", "poznaniu": "Poznań", "poznania": "Poznań",
    "gdansk": "Gdańsk", "gdansku": "Gdańsk", "gdanska": "Gdańsk",
    "gdynia": "Gdynia", "gdyni": "Gdynia", "szczecin": "Szczecin", "szczecinie": "Szczecin",
    "bydgoszcz": "Bydgoszcz", "bydgoszczy": "Bydgoszcz", "lublin": "Lublin",
    "lublinie": "Lublin", "bialystok": "Białystok", "bialymstoku": "Białystok",
    "katowice": "Katowice", "katowicach": "Katowice", "rzeszow": "Rzeszów",
    "rzeszowie": "Rzeszów", "torun": "Toruń", "toruniu": "Toruń", "kielce": "Kielce",
    "olsztyn": "Olsztyn", "olsztynie": "Olsztyn", "czestochowa": "Częstochowa",
    "czestochowie": "Częstochowa", "radom": "Radom", "sosnowiec": "Sosnowiec",
    "gliwice": "Gliwice", "zabrze": "Zabrze", "opole": "Opole", "plock": "Płock",
    "elblag": "Elbląg", "elblagu": "Elbląg", "zakopane": "Zakopane", "sopot": "Sopot",
}


def _city_variants(city):
    """Warianty nazwy do geokodowania: alias (z diakrytykami), oryginał, ASCII, odmiany."""
    alias = _CITY_ALIASES.get(normalize_facts(city).strip())
    out = [alias] if alias else []
    for base in (city, normalize_facts(city)):
        if not base:
            continue
        out.append(base)
        for suf in ("iu", "ie", "u", "em", "ego", "owi", "ach", "ami", "a", "y"):
            if base.endswith(suf) and len(base) > len(suf) + 2:
                out.append(base[: -len(suf)])
        if base.endswith("i") and len(base) > 3:
            out.append(base[:-1])
            out.append(base[:-1] + "a")
        out.append(base.rstrip("aeyu"))
    seen, uniq = set(), []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def weather_text(text="", fallback_city=""):
    city = extract_city(text) or fallback_city
    if not city:
        return "W jakim mieście sprawdzić pogodę?"
    try:
        place = None
        candidates = []
        for cand in _city_variants(city)[:6]:
            geo = _get_json("https://geocoding-api.open-meteo.com/v1/search?name="
                            + urllib.parse.quote(cand) + "&count=5&language=pl&format=json")
            candidates.extend(geo.get("results") or [])
        if candidates:
            # Preferuj Polskę i najludniejsze miasto (nie pierwszą wioskę o podobnej nazwie,
            # np. „krakowie" -> Krakowiec; „lodzi" -> Lodzianivka).
            place = max(candidates, key=lambda r: (r.get("country_code") == "PL",
                                                   r.get("population") or 0))
        if not place:
            return f"Nie znalazłam miejscowości {stt_fix.genitive_city(city)}."
        lat, lon = place["latitude"], place["longitude"]
        name = place.get("name") or city
        w = _get_json(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                      "&current=temperature_2m,wind_speed_10m,weather_code&timezone=auto")
        cur = w.get("current") or {}
        temp = cur.get("temperature_2m")
        wind = cur.get("wind_speed_10m")
        desc = _WMO.get(cur.get("weather_code"), "brak danych")
        return (f"Pogoda w {stt_fix.locative_city(name)}: {desc}, temperatura {temp} stopni "
                f"Celsjusza, wiatr {wind} kilometrów na godzinę.")
    except Exception as e:
        return f"Nie udało się pobrać pogody: {e}"


# --- kurs walut (must-have: PRZEWALUTOWANIE) ---------------------------------------------
# „aktualny kurs dolara/euro" -> kurs z NBP (tabela A) + przeliczenie na PLN. Offline: ostatni
# zapisany kurs z pamięci (cache). Deterministyczne, bez modelu.
_CURRENCIES = {
    "usd": ("USD", "dolara amerykańskiego"), "dolar": ("USD", "dolara amerykańskiego"),
    "dolara": ("USD", "dolara amerykańskiego"),
    "dolary": ("USD", "dolarów amerykańskich"), "dolarow": ("USD", "dolarów amerykańskich"),
    "eur": ("EUR", "euro"), "euro": ("EUR", "euro"),
    "gbp": ("GBP", "funta szterlinga"), "funt": ("GBP", "funta szterlinga"),
    "funta": ("GBP", "funta szterlinga"),
    "funty": ("GBP", "funtów szterlingów"), "funtow": ("GBP", "funtów szterlingów"),
    "chf": ("CHF", "franka szwajcarskiego"), "frank": ("CHF", "franka szwajcarskiego"),
    "franka": ("CHF", "franka szwajcarskiego"),
    "franki": ("CHF", "franków szwajcarskich"), "frankow": ("CHF", "franków szwajcarskich"),
    "jpy": ("JPY", "jena japońskiego"), "jen": ("JPY", "jena japońskiego"),
    "jena": ("JPY", "jena japońskiego"),
    "cny": ("CNY", "juana chińskiego"), "yuan": ("CNY", "juana chińskiego"),
    "juana": ("CNY", "juana chińskiego"),
}
_CURRENCY_TOKEN_RE = re.compile(
    r"\b(" + "|".join(sorted(_CURRENCIES, key=len, reverse=True)) + r")\b")
_CURRENCY_CACHE = os.path.join(str(config.LOGS_DIR), "currency_cache.json")


def _pl_num(v):
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def _load_currency_cache():
    try:
        with open(_CURRENCY_CACHE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_currency_cache(cache):
    try:
        os.makedirs(os.path.dirname(_CURRENCY_CACHE), exist_ok=True)
        with open(_CURRENCY_CACHE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False)
    except OSError:
        pass


def _currency_rate(code):
    """(rate, date) z NBP tabeli A; offline/awaria -> ostatni zapisany kurs (date z dopiskiem)."""
    cache = _load_currency_cache()
    try:
        data = _get_json(f"https://api.nbp.pl/api/exchangerates/rates/A/{code}/?format=json")
        r = (data.get("rates") or [])[0]
        rate, date = float(r["mid"]), str(r["effectiveDate"])
        cache[code] = {"rate": rate, "date": date}
        _save_currency_cache(cache)
        return rate, date
    except Exception:
        c = cache.get(code)
        if c and c.get("rate") is not None:
            return float(c["rate"]), f"{c.get('date', '?')} (z pamięci, offline)"
        return None, None


def currency_text(text):
    """„aktualny kurs dolara" -> kurs NBP w zł; opcjonalnie przeliczenie kwoty. None gdy brak waluty."""
    low = normalize_facts(text or "")
    m = _CURRENCY_TOKEN_RE.search(low)
    if not m:
        return None
    token = m.group(1)
    code, spoken = _CURRENCIES[token]
    amount = None
    am = re.search(r"(\d+(?:[.,]\d+)?)\s*" + re.escape(token), low)
    if am:
        try:
            amount = float(am.group(1).replace(",", "."))
        except ValueError:
            amount = None
    rate, date = _currency_rate(code)
    if rate is None:
        return f"Nie mam kursu {spoken} i brak połączenia z internetem."
    if amount is not None and amount != 1:
        return (f"Przeliczam: {_pl_num(amount)} {spoken} to {_pl_num(amount * rate)} złotych "
                f"(kurs {_pl_num(rate)} zł, NBP {date}).")
    return f"Kurs {spoken} to {_pl_num(rate)} zł (NBP, {date})."


def now_stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
