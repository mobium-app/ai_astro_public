"""Rejestr narzędzi: schemat + wykonanie + bramka bezpieczeństwa."""

import re
from dataclasses import dataclass, field

from .. import config
from ..safety import is_private_url, normalize_facts

SCOPES = {"read", "sandbox", "gated", "network"}

# Narzędzia NIE wystawiane modelowi (wywołuje je wyłącznie deterministyczny fast-path/
# potwierdzenie, np. zasilanie). Nie wchodzą do schematów, selekcji ani datasetu.
HIDDEN_TOOLS = {"power"}


@dataclass
class ToolResult:
    text: str
    ok: bool = True
    data: dict | None = None

    def __str__(self):
        return self.text


@dataclass
class ToolContext:
    settings: object = None
    memory: object = None
    confirmer: object = None
    registry: object = None
    backends: object = None
    log: object = print
    # Jednorazowe obejście bramki po tym, jak użytkownik potwierdził akcję (patrz core/pending.py).
    assume_confirmed: bool = False

    def workspace_path(self, path):
        from pathlib import Path
        base = Path(self.settings.WORKSPACE).resolve() if self.settings else None
        if base is None:
            return None
        raw = str(path or "").strip()
        if not raw:
            return None
        base.mkdir(parents=True, exist_ok=True)
        p = raw
        for pref in ("~/astro-agent/", "astro-agent/", str(base) + "/", "~/"):
            if p.startswith(pref):
                p = p[len(pref):]
                break
        cand = Path(p)
        if not cand.is_absolute():
            cand = base / cand
        cand = cand.resolve()
        if cand == base or str(cand).startswith(str(base) + "/"):
            return cand
        return None


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: object
    scopes: set = field(default_factory=lambda: {"read"})
    confirm_text: str = ""
    gate: object = None
    self_gated: bool = False


TOOL_HINTS = [
    # Wykonanie polecenia (użytkownik mówi „wykonaj polecenie/komendę X", „df -h", „ls").
    # MUSI być pierwszy: wcześniej „polecenie" łapało się na hint „cen" (cena) → web_search,
    # a run_command wypadał z budżetu → model nie mógł wykonać polecenia.
    (re.compile(r"wykonaj|uruchom|odpal|polecen|komend|\bdf\b|\bls\b|\bcat\b|\bdu\b|\bps\b|"
                r"\bwhoami\b|\buname\b"),
     {"run_command"}),
    (re.compile(r"temperatur|throttl|uptime|ram|pamie|dysk|miejsce|obciaz|zasob|procesor|system"),
     {"system_info", "run_command"}),
    (re.compile(r"zapamiet|pamiet|\bpamie"), {"remember"}),
    (re.compile(r"utworz|stworz|napisz|dopisz|notatk|zapisz\s+(?:to\s+)?(?:w\s+)?plik"),
     {"write_file", "append_file"}),
    (re.compile(r"przeczytaj|odczytaj|zawartosc|/etc/|/proc/|/var/|plik"),
     {"read_file", "list_dir", "search_files", "run_command"}),
    (re.compile(r"wylistuj|lista|katalog|folder"),
     {"list_dir", "search_files", "read_file", "run_command"}),
    (re.compile(r"znajdz|wyszuk|grep|wzorzec|dopasowan"),
     {"search_files", "run_command"}),
    (re.compile(r"w internecie|online|w sieci|najnowsz|aktualn|kurs|\bcen\w*|co to jest"),
     {"web_search", "web_fetch"}),
    (re.compile(r"http|stron|pobierz|wikipedia|adres|url"), {"web_fetch", "web_search"}),
    (re.compile(r"paczkomat|aptek|bankomat|sklep|restaurac|stacja|najbliz|poblizu"),
     {"nearby_places", "web_search"}),
    (re.compile(r"\bman\b|manual|podrecznik|opcje"), {"man_page", "cmd_help"}),
    (re.compile(r"--help|szybk[aey] pomoc|\bpomoc\b"), {"cmd_help", "man_page"}),
    (re.compile(r"sprawdz.*skrypt|weryfikuj.*(?:skrypt|skladni)|skladni|syntax|shellcheck"),
     {"check_script", "run_script"}),
    (re.compile(r"uruchom.*skrypt|wykonaj.*(?:skrypt|\.sh)|\.sh\b"), {"run_script", "check_script"}),
    (re.compile(r"skrypt|bash|python|shebang|shellcheck"),
     {"write_file", "append_file", "run_script", "check_script", "run_command"}),
    (re.compile(r"zainstaluj|skonfiguruj|uslug|systemd|apt|napraw|aktualiz"),
     {"system_task", "run_command"}),
    # Aktualizacja systemu przez apt (schemat treningu: update_system).
    (re.compile(r"zaktualizuj|aktualizacj|upgrade|apt\s+update|apt\s+upgrade"),
     {"update_system", "system_task", "run_command"}),
    # Zasilanie, gdy fast-path nie złapie (spójne ze schematem treningu: system_power).
    (re.compile(r"wylacz\s+(?:system|komputer|pi)|restart\w*|zrestartuj|reboot|shutdown|"
                r"zamknij\s+system"),
     {"system_power"}),
    # Dom / Home Assistant (MQTT): stan i sterowanie urządzeniami z whitelisty.
    (re.compile(r"\bdom\b|domu|domow|swiat[lł]|zarowk|gniazdk|mqtt|home\s+assistant|"
                r"urzadze\w*|temperatura\s+w\s+domu|wilgotnosc"),
     {"home_status", "home_command"}),
    # Kamera / wizja.
    (re.compile(r"kamer|spojrz|spojrzyj|zobacz\s+co|co\s+widzisz|zdjecie|obraz"),
     {"camera_look"}),
    # Katalog w piaskownicy agenta (tworzenie).
    (re.compile(r"utworz\s+katalog|nowy\s+katalog|zrob\s+katalog|mkdir|katalog\s+w\s+"),
     {"make_dir", "list_dir"}),
    # Skan sieci lokalnej (nmap) / Wi-Fi.
    (re.compile(r"skan\w*\s+siec|nmap|urzedzeni\w*\s+w\s+sieci|lokalna\s+siec|kto\s+jest\s+w\s+sieci"),
     {"network_scan", "wifi_scan"}),
    (re.compile(r"wifi|wi-?fi|siec\s+bezprzewodow|polacz\s+z\s+siec|rozlacz\w*\s+(?:z\s+)?(?:wifi|siec)"),
     {"wifi_scan", "wifi_connect", "wifi_disconnect"}),
    (re.compile(r"hailo|npu|telemetr|akcelerator"), {"npu_status", "system_info"}),
    (re.compile(r"przepis|skill|receptur|umiejetnos|procedur|lista uslug|dzialajace uslugi"),
     {"list_skills", "run_skill"}),
    (re.compile(r"\bgit\b|repozytori|status repo"), {"run_skill", "run_command"}),
    (re.compile(r"ile dokumentow|liczba dokumentow|liczb[eę] dokument"), {"knowledge_stats"}),
    (re.compile(r"\bco to jest|czym jest|kim jest|wyja[sś]nij|opowiedz|wiedz|dokumentacj|"
                r"pierwsza pomoc|objaw|boli|jak dzia[lł]a"), {"search_knowledge"}),
    # Kamera sieciowa = „oczy": podgląd, zdjęcie, obrót (PTZ), ocena otoczenia i osoby.
    (re.compile(r"kamer|obraz|zdj[eę]ci|wizj|sp[oó]jrz|popatrz|zobacz|co\s+widzisz|\boczy\b|"
                r"obr[oó][cć]|skieruj|wy[sś]rodkuj|ptz"), {"camera_look", "camera_move",
                                                          "camera_home"}),
    (re.compile(r"oce[nń]\s+otoczenie|rozejrzyj|co\s+si[eę]\s+dzieje|opisz\s+otoczenie|"
                r"\bscena\b|otoczenie"), {"camera_scene", "camera_look"}),
    (re.compile(r"kto\s+(?:to|jest|w\s+pokoju)|kogo\s+widzisz|ile\s+(?:os[oó]b|ludzi)|"
                r"rozpoznaj|znasz\s+(?:go|j[aą])|to\s+jest|zapami[eę]taj|zapomnij|"
                r"lista\s+os[oó]b|znane\s+osoby|kogo\s+znasz|kto\s+by[lł]|"
                r"kiedy\s+ostatnio\s+widzia|zobaczenia"),
     {"camera_people", "person_enroll", "person_forget", "person_list", "person_sightings"}),
    (re.compile(r"modele\s+wizji|status\s+wizji"), {"vision_status"}),
]
CORE_TOOLS = {"system_info", "ask_user"}
GENERAL_TOOLS = ["system_info", "read_file", "list_dir", "search_files", "run_command",
                 "web_search", "web_fetch", "ask_user"]
# Kolejność w budżecie promptu: niższe = bardziej szczegółowe/narzędziowe, wpychane PRZED ogólnymi
# (metryki held-out pokazały, że ogólne read_file/list_dir/run_command wypychały write_file/man_page
# itd. z puli MAX_TOOLS). Nie zmieniaj bez pomiaru `e6_gate --holdout`.
TOOL_PRIORITY = {
    "write_file": 0, "append_file": 0, "remember": 0, "man_page": 0, "cmd_help": 0,
    "check_script": 0, "run_script": 0, "web_fetch": 0, "search_knowledge": 0,
    "knowledge_stats": 0, "run_skill": 0, "list_skills": 0, "npu_status": 0,
    "system_task": 0, "nearby_places": 0, "ask_user": 0,
    "update_system": 0, "system_power": 0, "home_status": 0, "home_command": 0,
    "camera_look": 0, "make_dir": 0, "network_scan": 0, "wifi_scan": 0,
    "wifi_connect": 0, "wifi_disconnect": 0,
    "camera_move": 0, "camera_home": 0, "camera_snapshot": 0,
    "camera_scene": 0, "camera_people": 0, "person_enroll": 0, "person_forget": 0,
    "person_list": 0, "person_sightings": 0, "vision_status": 0,
    "vision_forget_unknowns": 0,
    "web_search": 1,
    "read_file": 2, "list_dir": 2, "search_files": 2, "run_command": 2,
    "system_info": 3,
}


class Registry:
    def __init__(self):
        self._tools = {}

    def tool(self, name, description="", parameters=None, scopes=("read",), confirm_text="",
             gate=None, self_gated=False):
        bad = set(scopes) - SCOPES
        if bad:
            raise ValueError(f"nieznany scope: {bad}")

        def deco(fn):
            self.register(name, description, parameters or {"type": "object", "properties": {}},
                          fn, set(scopes), confirm_text, gate, self_gated)
            return fn
        return deco

    def register(self, name, description, parameters, fn, scopes, confirm_text="", gate=None,
                 self_gated=False):
        if name in self._tools:
            raise ValueError(f"narzędzie już zarejestrowane: {name}")
        self._tools[name] = Tool(name, description, parameters, fn, set(scopes), confirm_text,
                                 gate, self_gated)
        return self._tools[name]

    def get(self, name):
        return self._tools.get(name)

    def names(self):
        return list(self._tools)

    def visible_names(self):
        """Nazwy narzędzi wystawianych modelowi (bez HIDDEN_TOOLS)."""
        return [n for n in self._tools if n not in HIDDEN_TOOLS]

    def schemas(self, only=None):
        names = set(self._tools) if only is None else (set(only) & set(self._tools))
        out = []
        for name in self._tools:
            if name in names and name not in HIDDEN_TOOLS:
                t = self._tools[name]
                out.append({"type": "function", "function": {
                    "name": t.name, "description": t.description,
                    "parameters": t.parameters}})
        return out

    def select_names(self, text, limit=None):
        """Podzbiór nazw narzędzi trafnych dla wypowiedzi (ograniczony budżet promptu).
        Rdzeń (system_info/ask_user) jest zawsze obecny; limit dobiera narzędzia trafne."""
        names = [n for n in self._tools if n not in HIDDEN_TOOLS]
        core = [n for n in CORE_TOOLS if n in names]
        limit = max(limit if limit is not None else config.MAX_TOOLS, len(core))
        t = normalize_facts(text or "")
        picked = set()
        matched = False
        for rx, tools in TOOL_HINTS:
            if rx.search(t):
                picked |= (tools & set(names))
                matched = True
        if not matched or not picked:
            pool = [n for n in GENERAL_TOOLS if n in names]
        else:
            pool = [n for n in names if n in picked and n not in core]
            # Najpierw narzędzia szczegółowe (write_file/man_page/...), potem ogólne
            # (read_file/list_dir/run_command) — inaczej ogólne wypychają trafne z budżetu.
            order = {n: i for i, n in enumerate(names)}
            pool.sort(key=lambda n: (TOOL_PRIORITY.get(n, 2), order.get(n, 0)))
        out = pool[:max(0, limit - len(core))]
        for name in core:
            if name not in out:
                out.append(name)
        return out[:limit]

    def select(self, text, limit=None):
        return self.schemas(only=self.select_names(text, limit))

    def execute(self, name, args, ctx):
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(f"nieznane narzędzie: {name}", ok=False)
        args = dict(args or {})
        if "network" in tool.scopes and args.get("url") and is_private_url(args["url"]):
            return ToolResult("odmowa: adres prywatny/lokalny (SSRF)", ok=False)
        if "gated" in tool.scopes and not tool.self_gated:
            if not getattr(ctx, "assume_confirmed", False):
                pre_ok = bool(tool.gate and tool.gate(args))
                if not pre_ok:
                    announce = tool.confirm_text or f"Wykonać {name}?"
                    ok = ctx.confirmer.require_confirm(announce, name, args) if ctx.confirmer else False
                    if not ok:
                        return ToolResult(f"Wymaga potwierdzenia: {announce}", ok=False,
                                          data={"pending": True, "kind": name, "payload": args})
        try:
            result = tool.fn(ctx, **args)
        except TypeError as e:
            return ToolResult(f"błąd argumentów {name}: {e}", ok=False)
        except Exception as e:
            return ToolResult(f"błąd {name}: {e}", ok=False)
        if isinstance(result, ToolResult):
            return result
        return ToolResult(str(result), ok=True)


registry = Registry()
tool = registry.tool
