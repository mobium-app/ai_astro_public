"""Komendy „must-have" (lista `/etc/astro-secrets/komendy_must-have`) - deterministyczny fast-path.

Zasada: te polecenia muszą działać GŁOSOWO i BEZWARUNKOWO (offline/online/remote_ai), bez modelu
i bez chmury, o ile w pliku nie napisano inaczej. Ten moduł obsługuje je lokalnie (regex + argv),
a `dispatch` woła go wcześnie - PRZED Wi-Fi i szybkimi ścieżkami - żeby np. „zasoby zdalne" nie
zostało przechwycone przez „zasoby systemowe", a „połącz z siecią numer 3" przez łączenie po nazwie.
"""

import os
import re
import shutil
import subprocess
import sys
import time

from .. import config, mirror
from ..safety import normalize_command, normalize_facts

# --- przerwanie / informacja zwrotna --------------------------------------------------------
_ABORT_RE = re.compile(
    r"^\s*(?:przerwij|zatrzymaj|stop|koniec|zatrzymaj\s+sie|przerwij\s+to)\s*[.!]?\s*$")
_FEEDBACK_NEG_RE = re.compile(
    r"^\s*(?:zle|beznadziejnie|blad|dramat|do\s+niczego|nie\s+tak|slabo|porazka)"
    r"(?:[\s,.]+\w+){0,2}\s*[.!]?\s*$")
_FEEDBACK_POS_RE = re.compile(
    r"^\s*(?:dobrze|okej|ok|super|spoko|swietnie|swietna|tak\s+trzymaj|brawo|pieknie|"
    r"jestes\s+super|dobra\s+robota|ladnie)(?:[\s,.]+\w+){0,2}\s*[.!]?\s*$")

# --- zasoby zdalne (remote_ai) --------------------------------------------------------------
_REMOTE_RES_RE = re.compile(
    r"\b(?:zasoby\s+(?:zdalne|remote)|remote\s+zasoby|zuzycie\s+(?:tokenow|remote|ai)|"
    r"raport\s+remote|stan\s+remote)\b")

# --- własne IP ------------------------------------------------------------------------------
_IP_RE = re.compile(
    r"^\s*(?:podaj\s+(?:swoje\s+|swoj\s+)?(?:adres\s+)?ip|jakie\s+masz\s+ip|moje\s+ip|"
    r"podaj\s+ip|adres\s+ip|ip|"
    r"(?:poka[zż]|wy[sś]wietl)\s+(?:swoje\s+|swoj\s+)?(?:adres\s+)?ip)\s*[.!]?\s*$")

# --- opencode -------------------------------------------------------------------------------
# Angielskie „opencode" użytkownik wymawia/zapisuje fonetycznie: „opencołd", „opencolt".
_OPENCODE_RE = re.compile(
    r"\b(?:opencode|open\s*code|open\s*co[lł]?[dt]|open\s*ko[lł]?[dt]|open\s*coat|openkod)\b")
_LAUNCH_VERB_RE = re.compile(r"\b(?:otworz|otworzyc|uruchom|odpal|wlacz|start)\w*\b")

# --- instalacja pakietu ---------------------------------------------------------------------
_INSTALL_RE = re.compile(
    r"\b(?:instaluj|zainstaluj)\s+(?:mi\s+)?"
    r"(?:aplikacj\w*|program\w*|pakiet\w*|apk[eę]|apke)?\s*"
    r"([a-z0-9][a-z0-9.+-]{1,40})")
_INSTALL_STOPWORDS = {"mi", "do", "na", "za", "sie", "prosze", "jakas", "jakis", "nowa", "nowy",
                      "program", "programy", "programu", "aplikacje", "aplikacja", "aplikacje",
                      "pakiet", "pakiety", "pakietu", "apke", "apka", "oprogramowanie"}

# --- najbliższe miejsce (POI) ---------------------------------------------------------------
# Szyki: „najbliższy paczkomat", „podaj adres najbliższej apteki", „gdzie jest paczkomat",
# „paczkomat w pobliżu". Uwaga: dopasowanie na tekście znormalizowanym (bez diakrytyków).
_NEARBY_RE = re.compile(
    r"\b(?:podaj\s+)?(?:adres\s+)?(?:najbli\w+|pobli\w+)\s+(.+?)\s*$"
    r"|\b(?:gdzie\s+jest|gdzie\s+mam|gdzie\s+znajde|gdzie\s+znajdę|gdzie\s+kupie)\s+"
    r"(?:najbli\w+|pobli\w+)?\s*(.+?)\s*$"
    r"|\b(.+?)\s+w\s+pobli\w+\b")

# --- propozycja posiłku ---------------------------------------------------------------------
_RECIPE_RE = re.compile(
    r"\b(?:zaproponuj|pomysl\s+na|podaj\s+pomysl\s+na|co\s+na|co\s+ugotowac|co\s+zjesc\s+na)\s+"
    r"(obiad|sniadanie|deser|kolacje|przekaske|lunch)\b")

# --- czułość / pochwała ---------------------------------------------------------------------
_AFFECTION_RE = re.compile(
    r"\b(?:lubisz\s+mnie|kochasz\s+mnie|co\s+o\s+mnie\s+myslisz|podoba\s+mi\s+sie|jestes\s+(?:super|"
    r"wspaniala|najlepsza|ladna|piekna|madra)|fajna\s+jestes|pieknie\s+(?:wygladas|mowisz)|"
    r"fajnie\s+sie\s+z\s+toba\s+rozmawia|gratulacje|komplement|pochwal\s+mnie|powiedz\s+cos\s+milego)\b")

# --- profil barwy głosu (czysty / robocik) --------------------------------------------------
# `_GLOS` celowo nie łapie „głośność/głośniej" (po „glos" musi być granica słowa).
_GLOS = r"glos(?:u|ie|em|owi)?\b"
_VOICE_CLEAN_RE = re.compile(
    rf"\b(?:czysty\s+{_GLOS}|{_GLOS}\s+bez\s+efekt\w*|bez\s+efekt\w*\s+{_GLOS}|"
    rf"wylacz\s+(?:efekt\w*\s+)?{_GLOS}|normaln\w+\s+{_GLOS})\b")
_VOICE_ROBOT_RE = re.compile(
    rf"\b(?:{_GLOS}\s+robocika|roboczy\s+{_GLOS}|{_GLOS}\s+robota|efekt\s+robocika|"
    rf"wlacz\s+(?:efekt\w*\s+)?{_GLOS}|przelacz\s+na\s+robocika)\b")

# --- tryby pracy (offline / komputer / premium) ---------------------------------------------
# Wymowa/zapis bywa fonetyczny: „oflajn", „kompjuter", „premiem". Wzorce patrzą na „tryb X",
# ale akceptują też samą nazwę trybu (offline/premium) lub czasownik przełączania. Uwaga: samo
# „komputer" NIE może przełączać (kolizja z komendami systemowymi typu „wyłącz komputer").
_MODE_VERB = r"(?:przelacz|przelacz\s+na|wlacz|ustaw|zmien|zmien\s+na|wrzuc)"
_MODE_OFFLINE_RE = re.compile(
    rf"^\s*(?:of+lajn|offline|off\s*-?\s*line|of\s*lajn|lokaln\w*)\s*[.!]?\s*$"
    rf"|\b(?:tryb|{_MODE_VERB})\s+(?:of+lajn|offline|off\s*-?\s*line|of\s*lajn|lokaln\w*)\b")
_MODE_KOMPUTER_RE = re.compile(
    rf"\b(?:(?:tryb|{_MODE_VERB})\s+)(?:komputer\w*|kompjuter\w*)\b")
_MODE_PREMIUM_RE = re.compile(
    rf"^\s*(?:premium|premiem|premijum|premiom|platn\w*)\s*[.!]?\s*$"
    rf"|\b(?:tryb|{_MODE_VERB})\s+(?:premium|premiem|premijum|premiom|platn\w*)\b")
# Status trybu/łączności: „jaki tryb", „status trybow", „melduj status" itp.
_MODE_STATUS_RE = re.compile(
    r"\b(?:tryb\s+status|jaki\s+(?:masz\s+)?tryb|status\s+(?:trybow|lacznosci|polaczenia)|"
    r"melduj\s+status|sprawdz\s+status|stan\s+lacznosci)\b")
# Raport łańcucha premium (monitoring): „premium status", „status premium".
_PREMIUM_STATUS_RE = re.compile(
    r"\b(?:premium\s+status|status\s+premium)\b")

# --- kamera sieciowa = „oczy" ASTRO ----------------------------------------------------------
# Sterowanie położeniem (PTZ) i podgląd. Determinizm: „obróć/popatrz + kierunek" = ruch; samo
# „spójrz/co widzisz" = klatka; „na wprost/wyśrodkuj" = pozycja domowa. Kamera nie wymaga modelu.
_CAM_WORD_RE = re.compile(r"\bkamer\w*|\boczy\b|\bwzrok\b|\bobiektyw\w*")
_CAM_VERB_RE = re.compile(
    r"\b(?:obr[oó][cć]\w*|skieruj\w*|przesu[ńn]\w*|wyceluj\w*|podnie[śs]\w*|opu[śs][cć]\w*|"
    r"dopasuj\w*|ustaw\w*|patrz\w*|popatrz\w*|sp[oó]jrz\w*|zobacz\w*|poka[zż]\w*)\b")
_CAM_STOP_RE = re.compile(
    r"\b(?:stop|zatrzymaj|st[oó]j|wstrzymaj)\s+(?:sie\s+)?(?:z\s+)?kamer\w*|"
    r"\bkamer\w*\s+(?:stop|st[oó]j)\b")
# Wybór kamery (wielokamera, Faza 3): numer („kamera 2", „z kamery 3", „na kamerze 2")
# albo słowo porządkowe („druga kamera", „kamera trzecia").
_CAM_NUM_RE = re.compile(
    r"\b(?:kamer\w*|na\s+kamer\w*|z\s+kamer\w*|przed\s+kamer\w*)\s+(?:numer\s*)?([0-9]{1,2})\b"
    r"|\b(?:pierwsza|druga|trzecia|czwarta|pi[ąa]ta)\s+(?:kamer\w*)\b"
    r"|\b(?:kamer\w*)\s+(?:numer\s*)?(?:pierwsza|druga|trzecia|czwarta|pi[ąa]ta)\b")
_CAM_HOME_RE = re.compile(
    r"\b(?:wy[sś]rodkuj|wyzeruj|ustaw|skieruj|obr[oó][cć])\w*\s+(?:sie\s+)?(?:do\s+)?"
    r"(?:(?:pierwsz|drug|trzec|czwart|pi[ąa]t)\w*\s+)?kamer\w*"
    r"[^.!?]{0,15}?\b(?:na\s+wprost|wprost|centrum|poziom|srodek|środek)\b|"
    r"\b(?:wy[sś]rodkuj|wyzeruj)\w*\s+(?:sie\s+)?"
    r"(?:(?:pierwsz|drug|trzec|czwart|pi[ąa]t)\w*\s+)?kamer\w*|"
    r"\bkamer\w*(?:\s+(?:numer\s*)?[0-9]{1,2}|\s+(?:pierwsza|druga|trzecia|czwarta|pi[ąa]ta))?"
    r"\s+(?:na\s+wprost|wprost|home|centrum|srodek|środek)\b|"
    r"\bkamer\w*\s+do\s+(?:centrum|srodka|środka)\b")
_CAM_LOOK_RE = re.compile(
    r"\bco\s+widzisz\b|\bsp[oó]jrz\b|\bpopatrz\b|\bpatrz\b|\bzobacz\b|"
    r"\bzr[oó]b\s+zdj[eę]ci\w*|\bzdj[eę]ci\w*\s+z\s+kamer\w*|\bzdj[eę]ci\w*\s+kamer\w*|"
    r"\bklatk\w*\s+z\s+kamer\w*|\bpokaz\s+obraz\b|\bco\s+jest\s+na\s+obrazie\b")
_CAM_STATUS_RE = re.compile(
    r"\bstatus\s+kamer\w*|\bkamer\w*\s+status\b|\bczy\s+widzisz\b|\bwidzisz\s+mnie\b|"
    r"\bpodl[aą]cz\s+kamer\w*|\bwl[aą]cz\s+kamer\w*|\bpol[aą]cz\w*[^.!?]{0,15}?\bkamer\w*|"
    r"\bustaw\s+kamer\w*\b\s*[.!]?$|"
    r"\b(?:ile|jakie|kt[oó]re|lista)\s+kamer\w*|\bkamer\w*\s+(?:lista|spis)\b|"
    r"\bile\s+masz\s+kamer\b")
# OCR (Faza 5): czytanie tekstu z kamery (kartka/ekran/dokument).
_CAM_OCR_RE = re.compile(
    r"\bprzeczytaj\b|\bodczytaj\b|\bco\s+(?:jest\s+)?(?:napisane|pisze|na\s+kartce)\b|"
    r"\btekst\s+z\s+kamer\w*|\bprzeczytaj\s+(?:kartk\w*|dokument|ekran|notatk\w*|kamer\w*)\b|"
    r"\bco\s+pisze\b|\bprzeczytaj\s+mi\b")
# Nasłuch (Faza 6): twardy „watch off/on".
_WATCH_OFF_RE = re.compile(
    r"\b(?:wyl[aą]cz|zatrzymaj|zako[nń]cz|wy[lł][aą]cz)\w*\s+(?:nas[lł]uch|obserwacj\w*|"
    r"watch)\b|\bzatrzymaj\s+nas[lł]uch\w*\b|\bwy[lł][aą]cz\s+oczy\b")
_WATCH_ON_RE = re.compile(
    r"\b(?:wl[aą]cz|uruchom|wzn[oó]w|przywr[oó][cć])\w*\s+(?:nas[lł]uch|obserwacj\w*|"
    r"watch)\b|\bwl[aą]cz\s+oczy\b")
# Kierunki (na tekście znormalizowanym, bez diakrytyków). Kolejność: pary przed pojedynczymi.
_CAM_DIRS = [
    (r"g[oó]r[aę]?\s+lewo|lewo\s+g[oó]r", "upleft"),
    (r"g[oó]r[aę]?\s+prawo|prawo\s+g[oó]r", "upright"),
    (r"do[lł]u?\s+lewo|lewo\s+do[lł]", "downleft"),
    (r"do[lł]u?\s+prawo|prawo\s+do[lł]", "downright"),
    (r"\bw\s+lewo\b|\blewo\b|\blewa\b", "left"),
    (r"\bw\s+prawo\b|\bprawo\b|\bprawa\b", "right"),
    (r"do\s+g[oó]ry|w\s+g[oó]r|g[oó]r[eę]\b|\bg[oó]ra\b|\bw\s+g[oó]r[eę]\b", "up"),
    (r"do\s+do[lł]u|w\s+do[lł]|\bdo[lł]\b|na\s+do[lł]|w\s+d[oó][lł]\b", "down"),
]
_CAM_DIR_NAMES = {
    "left": "w lewo", "right": "w prawo", "up": "w górę", "down": "w dół",
    "upleft": "w lewo i w górę", "upright": "w prawo i w górę",
    "downleft": "w lewo i w dół", "downright": "w prawo i w dół",
}


def _cam_direction(low):
    for rx, name in _CAM_DIRS:
        if re.search(rx, low):
            return name
    return ""


def _camera_spec(low):
    """Wyciąga wybór kamery z komendy: „2", „druga" albo None (główna)."""
    m = _CAM_NUM_RE.search(low or "")
    if not m:
        return None
    num = next((g for g in m.groups() if g), None)
    if num:
        return num
    frag = m.group(0).lower()
    for word in ("pierwsza", "druga", "trzecia", "czwarta", "piąta", "piata"):
        if word in frag:
            return word
    return None


# --- wizja AI: ocena otoczenia + rozpoznawanie osób ------------------------------------------
_VIS_SCENE_RE = re.compile(
    r"\boce[nń]\s+otoczenie\b|\brozejrzyj\s+si[eę]\b|\bopisz\s+otoczenie\b|"
    r"\bco\s+si[eę]\s+(?:dzieje|dzieje\s+wok[oó][lł])\b|\bjakie\s+jest\s+otoczenie\b|"
    r"\bco\s+widzisz\s+(?:wok[oó][lł]|dooko[łl]a)\b|\bjak\s+wygl[aą]da\s+otoczenie\b")
_VIS_WHO_RE = re.compile(
    r"\bile\s+(?:os[oó]b|ludzi)\b|\bkto\s+jest\s+w\s+(?:pokoju|kamerze|kadrze|obrazie)\b|"
    r"\bkogo\s+widzisz\b|\bkto\s+to\s+jest\s+na\s+obrazie\b|\bznasz\s+(?:go|j[aą])\b|"
    r"\b(pokaz|powiedz)\s+kto\s+to\b|\bkto\s+si[eę]\s+kr[eę]ci\b")
_VIS_ENROLL_RE = re.compile(r"\bzapami[eę]taj\b|\bzapisz\b")
_VIS_FORGET_RE = re.compile(r"\bzapomnij\b")
_VIS_STATUS_RE = re.compile(r"\bstatus\s+wizji\b|\bmodele\s+wizji\b|\bwizja\s+status\b")
_VIS_FORGET_UNK_RE = re.compile(
    r"\bwykasuj\s+zobaczenia\b|\bwyczy[sś][cć]\s+zobaczenia\b|\busu[nń]\s+zobaczenia\b|"
    r"\bwyczy[sś][cć]\s+histori[eę]\s+os[oó]b\b|\bczyszczenie\s+zobacze[nń]\b")
_VIS_LIST_RE = re.compile(r"\blista\s+os[oó]b\b|\bznane\s+osoby\b|\bkogo\s+znasz\b|"
                          r"\bile\s+os[oó]b\s+znasz\b|\bjakie\s+osoby\s+znasz\b|"
                          r"\bkogo\s+zapami[eę]ta[łl]")
_VIS_SEEN_RE = re.compile(
    r"\bkto\s+by[lł]\s+(?:dzi[sś]|dzisiaj|wczoraj|w\s+domu|w\s+pokoju|u\s+mnie)\b|"
    r"\bkto\s+(?:tu|dzisiaj)\s+by[lł]\b|\bkto\s+by[lł]\b|"
    r"\bkiedy\s+ostatnio\s+(?:widzia[łl]|by[lł])\b|\bzobaczenia\b|\bkto\s+si[eę]\s+pojawi[łl]\b")
_VIS_EVENTS_RE = re.compile(
    r"\bco\s+za[uu]wa[zż]y[łl](?:[ae]?[sś])?\b|\bco\s+(?:si[eę]|to)\s+dzia[łl]o\b|"
    r"\bco\s+si[eę]\s+wydarzy[łl]o\b|\bjakie\s+zdarzenia\b|\bzdarzenia\s+(?:z\s+)?kamery\b|"
    r"\bco\s+s[łl]ycha[cć]\s+(?:u|z)\s+kamery\b|\bco\s+widzia[łl](?:a[sś])?\s+(?:przed\s+)?"
    r"(?:kamer[ąa]|na\s+obrazie)\b|\bco\s+si[eę]\s+dzieje\s+z\s+kamer[ąa]\b")
_OCR_RECENT_RE = re.compile(
    r"\bco\s+(?:by[łl]o|jest)\s+(?:napisane|napisa[łl]e[sś])\b|\bco\s+przeczyta[łl](?:a[sś])?\b|"
    r"\bco\s+odczyta[łl](?:a[sś])?\b|\bostatni\s+odczyt\b|\bco\s+(?:by[łl]o\s+)?na\s+kartce\b")
_VIS_NAME_STOP = {
    "mnie", "moje", "moja", "moj", "te", "ta", "to", "ten", "osobe", "osoba", "osoby",
    "jako", "jest", "ze", "za", "i", "a", "the", "kamera", "kamery", "zdjecie", "zdjecia",
    "dobrze", "dobra", "dobre", "tak", "nie", "prosze", "jak", "ma", "na", "w", "z",
    "twarz", "twarzy", "obraz", "zdjecie", "tej", "tego", "ten", "tam",
}


def _vis_name(text, trigger):
    """Wyciąga imię z „zapamiętaj/zapisz ... X" albo „zapomnij ... X" (ostatni sensowny token)."""
    low = normalize_command(text or "")
    m = re.search(trigger + r"\b(.*)$", low)
    if not m:
        return ""
    toks = [t for t in re.findall(r"[a-z]+", m.group(1)) if t not in _VIS_NAME_STOP]
    return toks[-1] if toks else ""


# --- profil relacji (P3) ---------------------------------------------------------------------
_RELATION_RE = re.compile(
    r"\b(?:nasza\s+relacja|profil\s+relacji|jak\s+(?:dlugo\s+)?sie\s+znamy|"
    r"jak\s+dlugo\s+sie\s+znamy|od\s+jak\s+dawna\s+sie\s+znamy|ile\s+rozmow\s+za\s+nami)\b")

# --- pamięć kontekstu (P4) -------------------------------------------------------------------
# Toleruje warianty STT: „pamięta"/„pamiętasz"/„pamięć" i szyk „sprawdź czy pamięta kontekst".
_CONTEXT_RE = re.compile(
    r"\b(?:czy\s+)?pamieta(?:sz|m)?\b[^.!?]{0,30}\bkontekst\w*|"
    r"\bkontekst\w*\b[^.!?]{0,25}\b(?:pamiet\w+|pamiec|wiesz)\b|"
    r"\b(?:ostatni|stan|pamiec|skrot)\s+kontekst\w*|"
    r"\bile\s+pamietasz\b|\bjak\s+dlugo\s+pamietasz\b|\bco\s+pamietasz\b")

# --- ulubione zwierzę (persona, offline) -----------------------------------------------------
_FAV_ANIMAL_RE = re.compile(
    r"\b(?:jakie\s+jest\s+twoje\s+ulubione\s+zwierz\w*|ulubione\s+zwierz\w*|moje\s+ulubione\s+zwierz\w*|"
    r"zwierzadko|zwierzatko)\b")

_RECIPES = {
    "sniadanie": ["jajecznica z pomidorami i chlebem", "owsianka z owocami i orzechami",
                  "kanapki z twarożkiem i rzodkiewką", "naleśniki z jogurtem"],
    "obiad": ["makaron z sosem pomidorowym i bazylią", "kurczak z ryżem i warzywami",
              "zupa pomidorowa z makaronem", "placki ziemniaczane ze śmietaną",
              "gulasz warzywny z kaszą"],
    "kolacje": ["sałatka z tuńczykiem", "omlet z warzywami", "tosty z serem i pomidorami",
                "zupa krem z dyni"],
    "deser": ["szybkie ciasto jogurtowe", "mus z jabłek z cynamonem", "kisiel owocowy",
              "czekoladowe brownie"],
    "przekaske": ["hummus z marchewką", "kanapka z awokado", "jogurt z granolą"],
    "lunch": ["wrap z kurczakiem", "sałatka cesarska", "zupa krem z pomidorów"],
}


def _ctx(agent):
    return getattr(agent, "ctx", None)


def _memory(agent):
    return getattr(agent, "memory", None) or getattr(_ctx(agent), "memory", None)


def _run(argv, timeout=30):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except Exception as e:
        return 1, str(e)


def _abort():
    # Przerwij bieżące odtwarzanie (długa odpowiedź) i poproś, by nie kontynuować.
    for proc in ("aplay", "sox"):
        try:
            subprocess.run(["pkill", "-x", proc], capture_output=True, timeout=5)
        except Exception:
            pass
    return "Zatrzymuję.", "abort"


def _remote_resources():
    script = os.path.join(str(config.REPO), "scripts", "remote_usage.py")
    code, tree = _run([sys.executable, script, "--all", "--no-color"], timeout=60)
    _code2, summary = _run([sys.executable, script, "--all", "--summary"], timeout=60)
    if tree:
        try:
            mirror.wall_write(tree)
        except Exception:
            pass
    return (summary or "Brak danych o zużyciu zdalnych modeli."), "remote-usage"


def _own_ip():
    code, out = _run(["ip", "-o", "-f", "inet", "addr", "show"], timeout=10)
    if code != 0:
        return "Nie mogę odczytać adresu IP."
    candidates = []
    for line in out.splitlines():
        m = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)/", line)
        if not m or m.group(1).startswith("127."):
            continue
        iface = line.split()[1] if len(line.split()) > 1 else ""
        prio = 0 if iface.startswith(("wl", "eth")) else 1
        candidates.append((prio, iface, m.group(1)))
    if not candidates:
        return "Nie znalazłam adresu IP w sieci lokalnej."
    candidates.sort()
    iface, ip = candidates[0][1], candidates[0][2]
    return f"Mój adres IP w sieci lokalnej to {ip} ({iface}).", "ip"


def _opencode_path():
    for p in (shutil.which("opencode"), os.path.expanduser("~/.opencode/bin/opencode")):
        if p and os.path.exists(p):
            return p
    return None


def _launch_opencode():
    path = _opencode_path()
    if not path:
        return "Nie znalazłam programu opencode.", "launch"
    home = os.path.expanduser("~")
    # Headless: uruchom na wolnym VT (TUI), bez przełączania ekranu. Fallback: proces w tle.
    if shutil.which("openvt"):
        for vt in range(2, 10):
            code, _out = _run(["sudo", "-n", "openvt", "-f", "-c", str(vt), "--",
                               "runuser", "-u", os.environ.get("USER", "shepard"), "--",
                               "env", f"HOME={home}", "TERM=linux", path], timeout=15)
            if code == 0:
                return (f"Otwieram OpenCode na konsoli — przejdź na ekran kontrol alt F{vt}.",
                        "launch")
    log = os.path.join(str(config.LOGS_DIR), "opencode.out")
    try:
        with open(log, "a", encoding="utf-8") as fh:
            subprocess.Popen([path], stdout=fh, stderr=fh, stdin=subprocess.DEVNULL,
                             start_new_session=True, cwd=home, env={**os.environ, "HOME": home})
        return f"Uruchomiłam OpenCode w tle (log: {log}).", "launch"
    except Exception as e:
        return f"Nie udało się uruchomić OpenCode: {e}", "launch"


def _last_user_text(agent):
    mem = _memory(agent)
    if mem is None:
        return ""
    try:
        rows = mem.conversations(6)
    except Exception:
        return ""
    for row in reversed(rows):
        if isinstance(row, dict) and row.get("role") in ("user", "ty") and row.get("text"):
            return row["text"]
    return ""


def _record_feedback_lesson(agent, feedback):
    """Zapisuje negatywną informację zwrotną jako „lekcję" (trafia do kontekstu modelu)."""
    mem = _memory(agent)
    if mem is None:
        return
    last = _last_user_text(agent)
    note = (f"użytkownik uznał poprzednią odpowiedź za błędną ({feedback})"
            + (f" przy zapytaniu „{last}”" if last else "")
            + " — popraw wykonanie i ton.")
    try:
        mem.add_lesson(note)
    except Exception:
        pass


def _set_mode(route):
    """Przełącza tryb pracy i zwraca (zapowiedź głosowa, route). Deterministyczne, bez modelu."""
    from ..backends import modes
    mode = {"mode-offline": modes.OFFLINE, "mode-komputer": modes.KOMPUTER,
            "mode-premium": modes.PREMIUM}.get(route)
    if not mode:
        return None
    modes.set_mode(mode)
    # Realny status łączności (sieć Wi-Fi / tunel do PC / remote_ai / OpenCode) — bez modelu,
    # bez halucynacji. Gdy zaplecze trybu nie działa, mówi wprost „Pracuję lokalnie".
    try:
        from . import conn_status
        reply = conn_status.mode_reply(mode)
    except Exception:
        reply = modes.announce(mode)
    return reply, route


def _mode_status():
    """Meldunek: aktywny tryb pracy + gotowość łańcuchów i tuneli. Bez modelu."""
    from ..backends import modes
    line = modes.status_line()
    try:
        from . import conn_status
        # Sieć / tunel PC-Kali / remote_ai / opencode / tunel Pi4 skynet.
        snap = conn_status.snapshot_text(deep=False)
        return (f"{line}. Łańcuchy i tunele: {snap}.", "mode-status")
    except Exception:
        return line, "mode-status"


def _premium_status():
    """Raport łańcucha premium z monitoringu (runtime/premium_status.json). Bez modelu.

    Czytany stan zapisuje cron (`scripts/premium_check.py`, co 10 min); gdy raportu
    nie ma — mówi wprost, że monitoring jeszcze nie wystartował."""
    import json as _json
    import time as _time
    from .. import config as _config

    path = _config.RUNTIME_DIR / "premium_status.json"
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
        items = data.get("items") or []
        age = max(0, int(_time.time() - float(data.get("ts") or 0)))
    except Exception:
        return ("Nie mam jeszcze raportu monitoringu premium.", "premium-status")
    parts = [f"{it.get('name', '?')} - {'OK' if it.get('ok') else 'BRAK'}" for it in items]
    if age < 120:
        when = "przed chwilą"
    elif age < 3600:
        when = f"{age // 60} min temu"
    else:
        when = f"{age // 3600} h temu"
    return ("Łańcuch premium: " + ", ".join(parts) + f" (stan sprzed {when}).",
            "premium-status")


def _camera_move(direction, spec=None):
    """Obraca wybraną kamerę sieciową (PTZ) deterministycznie — bez modelu."""
    from ..tools import vision
    if not vision.network_camera_enabled():
        return "Kamera sieciowa jest wyłączona.", "camera-move"
    cam, err = vision.camera_select(spec)
    if err:
        return err, "camera-move"
    if not cam["ptz"]:
        return f"Kamera {cam['name']} nie ma sterowania PTZ.", "camera-move"
    try:
        vision.ptz_nudge(direction, camera=cam)
    except Exception as e:
        return f"Nie mogę obrócić kamery: {e}", "camera-move"
    return (f"Obracam kamerę {cam['name']} {_CAM_DIR_NAMES.get(direction, direction)}.",
            "camera-move")


def _camera_home(spec=None):
    from ..tools import vision
    if not vision.network_camera_enabled():
        return "Kamera sieciowa jest wyłączona.", "camera-home"
    cam, err = vision.camera_select(spec)
    if err:
        return err, "camera-home"
    if not cam["ptz"]:
        return f"Kamera {cam['name']} nie ma sterowania PTZ.", "camera-home"
    try:
        vision.ptz_home(camera=cam)
    except Exception as e:
        return f"Nie mogę wyśrodkować kamery: {e}", "camera-home"
    return f"Ustawiam kamerę {cam['name']} na wprost.", "camera-home"


def _camera_look(spec=None):
    from ..tools import vision
    if not vision.camera_present():
        return "Nie mam podłączonej kamery.", "camera-look"
    cam, err = vision.camera_select(spec)
    if err:
        return err, "camera-look"
    if not (cam["enabled"] and cam["host"] and cam["rtsp"]):
        return f"Kamera {cam['name']} jest wyłączona.", "camera-look"
    if not vision.camera_reachable(cam):
        return f"Kamera {cam['name']} nie odpowiada — sprawdź zasilanie i sieć.", "camera-look"
    frame = vision.capture_frame(camera=cam)
    if not frame:
        return "Kamera jest, ale nie mogę pobrać obrazu.", "camera-look"
    if vision.vlm_ready():
        return "Mam klatkę z kamery, ale opis obrazu nie jest jeszcze podłączony.", "camera-look"
    return ("Robię zdjęcie z kamery. Zapisane — opis obrazu dołożę, gdy podłączysz VLM.",
            "camera-look")


def _camera_status(spec=None):
    from ..tools import vision
    if not vision.network_camera_enabled():
        return "Kamera sieciowa jest wyłączona.", "camera-status"
    if spec:
        cam, err = vision.camera_select(spec)
        if err:
            return err, "camera-status"
        if vision.camera_reachable(cam):
            ptz = " z PTZ" if cam["ptz"] else " (bez PTZ)"
            return (f"Kamera {cam['name']} ({cam['host']}) działa{ptz}. Mogę patrzeć"
                    f"{' i obracać w lewo, prawo, w górę i w dół.' if cam['ptz'] else '.'}"),
            "camera-status"
        return f"Kamera {cam['name']} ({cam['host']}) nie odpowiada.", "camera-status"
    cams = vision.camera_sources()
    parts = [f"{i}: {c['name']} ({c['host']})" + (" PTZ" if c["ptz"] else "")
             for i, c in enumerate(cams, start=1)]
    return (f"Mam {len(cams)} kamer{'ę' if len(cams) == 1 else 'y'}: "
            + "; ".join(parts) + "."), "camera-status"


def _install(agent, pkg, goal):
    ctx = _ctx(agent)
    if ctx is None:
        return None
    if not re.match(r"^[a-z0-9][a-z0-9.+-]{1,40}$", pkg or ""):
        return f"Niepoprawna nazwa pakietu: {pkg!r}.", "install"
    steps = [{"command": f"sudo -n apt-get install -y {pkg}", "root": True}]
    plan_text = f"Plan: sudo apt-get install -y {pkg}"
    if not getattr(ctx, "assume_confirmed", False):
        conf = getattr(ctx, "confirmer", None)
        if conf is None or not conf.require_confirm(f"{plan_text} — wykonać?", "system_task",
                                                    {"steps": steps, "goal": goal}):
            return plan_text, "install"
    from ..tools.tasks import execute_steps
    return execute_steps(ctx, goal, steps).text, "install"


def _nearby(agent, text):
    from ..tools.web import nearby_kind, nearby_places_text
    low = normalize_facts(text)
    m = _NEARBY_RE.search(low)
    if not m:
        return None
    tail = next((g for g in m.groups() if g), text)
    kind = nearby_kind(tail)
    if not kind:
        return None
    location = ""
    mem = _memory(agent)
    store = getattr(mem, "profiles", None) if mem is not None else None
    if store is not None:
        prof = store.get() or {}
        from ..user import profile as P
        location = P.home_location(prof) or prof.get("city", "")
    return nearby_places_text(kind, location), "nearby"


def _context_status(agent):
    """Zgłasza, jak długo ASTRO pamięta kontekst (P4): digesty dzienne + pamięć bieżącej sesji."""
    days = int(getattr(config, "CONTEXT_DAYS", 7))
    turns = int(getattr(config, "SESSION_TURNS", 6))
    gap = int(getattr(config, "SESSION_GAP_S", 900))
    digests = 0
    mem = _memory(agent)
    try:
        if mem is not None:
            digests = len(mem.context_digests(limit=days + 2))
    except Exception:
        pass
    gap_txt = f"{gap // 60} min" if gap < 3600 else f"{gap // 3600} godz"
    return (f"Pamiętam kontekst trwały z ostatnich {days} dni (zapisane skróty dni: {digests}). "
            f"Bieżącą rozmowę trzymam jako ostatnie {turns} tur, a przerwa czyszcząca wątek to "
            f"{gap_txt}. Dążę do trwałego zapisu wszystkiego z odsiewem tylko wartościowego.",
            "context")


def _recipe(low):
    m = _RECIPE_RE.search(low)
    if not m:
        return None
    meal = m.group(1)
    meal = "kolacje" if meal == "kolacja" else meal
    options = _RECIPES.get(meal) or _RECIPES["obiad"]
    pick = options[int(time.time() // 86400) % len(options)]
    name = {"sniadanie": "Na śniadanie", "obiad": "Na obiad", "kolacje": "Na kolację",
            "deser": "Na deser", "przekaske": "Na przekąskę", "lunch": "Na lunch"}.get(meal, "Proponuję")
    return f"{name} proponuję {pick}. Chcesz przepis krok po kroku?", "recipe"


_WIFI_NUMBER_RE = re.compile(
    r"\b(?:polacz|podlacz|dolacz|wejdz|wejd[zż])\w*[^.!?]*\b(?:numer|nr|numerze)\s+(\d{1,2})\b")


def intent(text):
    """Czysty klasyfikator must-have (bez I/O): zwraca etykietę trasy albo "".

    Używany przez `handle` oraz przez audyt `scripts/must_have_audit.py` (porównanie listy
    `/etc/astro-secrets/komendy_must-have` ze stanem ASTRO) - dzięki temu audyt nie ma efektów."""
    low = normalize_command(text or "")
    if not low:
        return ""
    if _ABORT_RE.match(low):
        return "abort"
    if _REMOTE_RES_RE.search(low):
        return "remote-usage"
    if _IP_RE.match(low):
        return "ip"
    if _FEEDBACK_NEG_RE.match(low):
        return "feedback-neg"
    if _FEEDBACK_POS_RE.match(low):
        return "feedback-pos"
    if _AFFECTION_RE.search(low):
        return "affection"
    if _VOICE_CLEAN_RE.search(low):
        return "voice-clean"
    if _VOICE_ROBOT_RE.search(low):
        return "voice-robot"
    if _MODE_OFFLINE_RE.search(low):
        return "mode-offline"
    if _MODE_KOMPUTER_RE.search(low):
        return "mode-komputer"
    if _PREMIUM_STATUS_RE.search(low):
        return "premium-status"
    if _MODE_PREMIUM_RE.search(low):
        return "mode-premium"
    if _MODE_STATUS_RE.search(low):
        return "mode-status"
    if _WATCH_OFF_RE.search(low):
        return "watch-off"
    if _WATCH_ON_RE.search(low):
        return "watch-on"
    if _CAM_STOP_RE.search(low):
        return "camera-stop"
    if _CAM_HOME_RE.search(low):
        return "camera-home"
    if _CAM_OCR_RE.search(low):
        return "camera-ocr"
    _cam_dir = _cam_direction(low)
    if _cam_dir and (_CAM_WORD_RE.search(low) or _CAM_VERB_RE.search(low)):
        return "camera-move"
    if _CAM_LOOK_RE.search(low):
        return "camera-look"
    if _CAM_STATUS_RE.search(low):
        return "camera-status"
    if _VIS_SCENE_RE.search(low):
        return "vision-scene"
    if _VIS_SEEN_RE.search(low) and not _VIS_FORGET_UNK_RE.search(low):
        return "vision-seen"
    if _VIS_EVENTS_RE.search(low):
        return "vision-events"
    if _OCR_RECENT_RE.search(low):
        return "ocr-recent"
    if _VIS_FORGET_UNK_RE.search(low):
        return "vision-cleanseen"
    if _VIS_LIST_RE.search(low):
        return "vision-people"
    if _VIS_WHO_RE.search(low):
        return "vision-who"
    if _VIS_FORGET_RE.search(low):
        return "vision-forget"
    if _VIS_ENROLL_RE.search(low):
        return "vision-enroll"
    if _VIS_STATUS_RE.search(low):
        return "vision-status"
    if _CONTEXT_RE.search(low):
        return "context"
    if _FAV_ANIMAL_RE.search(low):
        return "fav-animal"
    if _RELATION_RE.search(low):
        return "relation"
    if _OPENCODE_RE.search(low):
        # Sam „opencode"/fonetyczne „opencołd" też ma otwierać program (1:1 z plikiem).
        rest = _OPENCODE_RE.sub("", low).strip(" .!?,")
        if not rest or _LAUNCH_VERB_RE.search(low):
            return "launch"
    if _WIFI_NUMBER_RE.search(low):
        return "wifi-number"
    if _INSTALL_RE.search(low):
        return "install"
    if _NEARBY_RE.search(low):
        from ..tools.web import nearby_kind
        _m = _NEARBY_RE.search(low)
        _tail = next((g for g in _m.groups() if g), low)
        if nearby_kind(_tail):
            return "nearby"
    if _RECIPE_RE.search(low):
        return "recipe"
    return ""


def handle(text, agent=None):
    """Zwraca (reply, route) albo None. Deterministyczny; bez modelu."""
    route = intent(text)
    if not route:
        return None
    low = normalize_command(text or "")

    # „przerwij/anuluj" w trakcie oczekiwania na hasło Wi-Fi obsługuje ścieżka Wi-Fi, nie abort.
    if route == "abort":
        if getattr(_ctx(agent), "wifi_pending", None):
            return None
        return _abort()
    if route == "remote-usage":
        return _remote_resources()
    if route == "ip":
        return _own_ip()
    if route == "feedback-neg":
        _record_feedback_lesson(agent, text)
        return "Przepraszam, poprawię się. Powiedz, co zrobić inaczej.", "feedback-neg"
    if route == "feedback-pos":
        return "Dziękuję! Cieszę się, że pomogłam.", "feedback-pos"
    if route == "affection":
        return "Też Cię lubię — dobrze mi z Tobą pracować.", "affection"
    if route == "voice-clean":
        from ..audio import voice_style
        voice_style.set_profile("clean")
        return "Przełączam na czysty głos, bez efektu robocika.", "voice-profile"
    if route == "voice-robot":
        from ..audio import voice_style
        voice_style.set_profile("robocik")
        return "Włączam głos robocika.", "voice-profile"
    if route in ("mode-offline", "mode-komputer", "mode-premium"):
        return _set_mode(route)
    if route == "mode-status":
        return _mode_status()
    if route == "premium-status":
        return _premium_status()
    if route == "watch-off":
        from ..vision import privacy
        privacy.set_watch_off(True)
        privacy.audit("watch_off", note="komenda głosowa")
        return "Wyłączam nasłuch kamery. Nie będę obserwować otoczenia.", "watch-off"
    if route == "watch-on":
        from ..vision import privacy
        privacy.set_watch_off(False)
        privacy.audit("watch_on", note="komenda głosowa")
        return "Włączam nasłuch kamery. Znowu widzę otoczenie.", "watch-on"
    if route == "camera-stop":
        from ..tools import vision
        try:
            vision.ptz_nudge("center", ms=0)
        except Exception as e:
            return f"Nie mogę zatrzymać kamery: {e}", "camera-stop"
        return "Zatrzymuję kamerę.", "camera-stop"
    if route == "camera-home":
        return _camera_home(_camera_spec(low))
    if route == "camera-move":
        return _camera_move(_cam_direction(low), _camera_spec(low))
    if route == "camera-look":
        return _camera_look(_camera_spec(low))
    if route == "camera-ocr":
        from ..tools import registry as _reg
        ctx = _ctx(agent)
        if ctx is None:
            return "Nie mogę teraz odczytać tekstu.", route
        args = {"camera": _camera_spec(low)} if _camera_spec(low) else {}
        return _reg.execute("camera_ocr", args, ctx).text, route
    if route == "ocr-recent":
        from ..tools import registry as _reg
        ctx = _ctx(agent)
        if ctx is None:
            return "Nie mogę teraz sprawdzić odczytów.", route
        return _reg.execute("ocr_recent", {}, ctx).text, route
    if route == "vision-events":
        from ..tools import registry as _reg
        ctx = _ctx(agent)
        if ctx is None:
            return "Nie mogę teraz sprawdzić zdarzeń z kamery.", route
        return _reg.execute("vision_events", {}, ctx).text, route
    if route == "camera-status":
        return _camera_status(_camera_spec(low))
    if route in ("vision-scene", "vision-who", "vision-status", "vision-people",
                 "vision-seen", "vision-cleanseen"):
        from ..tools import registry as _reg
        names = {"vision-scene": "camera_scene", "vision-who": "camera_people",
                 "vision-status": "vision_status", "vision-people": "person_list",
                 "vision-seen": "person_sightings", "vision-cleanseen": "vision_forget_unknowns"}
        period = "week" if re.search(r"tydzie", low) else "today"
        args = {"period": period} if route == "vision-seen" else {}
        ctx = _ctx(agent)
        if ctx is None:
            return "Nie mogę teraz użyć kamery.", route
        res = _reg.execute(names[route], args, ctx)
        return res.text, route
    if route == "vision-enroll":
        name = _vis_name(text, r"\b(?:zapamietaj|zapisz)")
        if not name:
            return ("Jak mam zapamiętać tę osobę? Powiedz: zapamiętaj, to jest <imię>.",
                    route)
        from ..tools import registry as _reg2
        return _reg2.execute("person_enroll", {"name": name}, _ctx(agent)).text, route
    if route == "vision-forget":
        name = _vis_name(text, r"\bzapomnij")
        if not name:
            return "Kogo mam zapomnieć?", route
        from ..tools import registry as _reg3
        return _reg3.execute("person_forget", {"name": name}, _ctx(agent)).text, route
    if route == "context":
        return _context_status(agent)
    if route == "fav-animal":
        return ("Mój ulubiony zwierzak to ośmiornica — jest mądra, ma osiem ramion i świetnie radzi "
                "sobie z problemami, trochę jak ja. A Ty jakie zwierzęta lubisz?", "affection")
    if route == "relation":
        from . import relationship
        return relationship.report(agent)
    if route == "launch":
        return _launch_opencode()
    if route == "wifi-number":
        from .. import wifi
        m = _WIFI_NUMBER_RE.search(low)
        target, err = wifi.connect_by_index(int(m.group(1)))
        if err:
            return err, "wifi"
        if wifi.is_secured(target):
            setattr(_ctx(agent), "wifi_pending", {"ssid": target})
            return "sieć zabezpieczona. podaj hasło", "wifi-password"
        _ok, msg = wifi.connect(target, None)
        return msg, "wifi"
    if route == "install":
        pkg = _INSTALL_RE.search(low).group(1)
        if pkg in _INSTALL_STOPWORDS:
            return "Jaką aplikację mam zainstalować? Podaj nazwę pakietu.", "install"
        return _install(agent, pkg, text)
    if route == "nearby":
        near = _nearby(agent, text)
        if near:
            return near
    if route == "recipe":
        rec = _recipe(low)
        if rec:
            return rec
    return None


__all__ = ["handle", "intent"]
