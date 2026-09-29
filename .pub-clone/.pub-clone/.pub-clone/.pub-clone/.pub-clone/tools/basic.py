"""Podstawowe narzędzia ASTRO (lokalne/odczyt, piaskownica, sieć)."""

import os
import re
import shutil
import subprocess
import time

from .. import mirror
from ..safety import (agent_readonly_ok, command_touches_secret, is_blocked_command,
                      is_sensitive_path, safe_write_path)
from .registry import ToolResult, tool

_REGISTERED = False


def _human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


def _cpu_temp():
    for zone in ("/sys/class/thermal/thermal_zone0/temp",
                 "/sys/class/hwmon/hwmon0/temp1_input"):
        try:
            with open(zone) as f:
                return int(f.read().strip()) / 1000.0
        except Exception:
            continue
    return None


def _meminfo():
    data = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                data[key.strip()] = int(rest.split()[0]) * 1024
    except Exception:
        pass
    return data


def _uptime():
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
    except Exception:
        return "?"
    days, rem = divmod(int(secs), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days} d")
    if hours or days:
        parts.append(f"{hours} godz.")
    parts.append(f"{minutes} min")
    return " ".join(parts)


def collect_system_info(path="/"):
    temp = _cpu_temp()
    disk = shutil.disk_usage(path)
    mem = _meminfo()
    total_mem = mem.get("MemTotal", 0)
    avail_mem = mem.get("MemAvailable", 0)
    return {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "uptime": _uptime(),
        "cpu_temp_c": round(temp, 1) if temp is not None else None,
        "disk_total_gb": round(disk.total / 1e9, 1),
        "disk_free_gb": round(disk.free / 1e9, 1),
        "disk_used_pct": round(100 * disk.used / disk.total, 1) if disk.total else 0,
        "mem_total_gb": round(total_mem / 1e9, 1),
        "mem_available_gb": round(avail_mem / 1e9, 1),
    }


def register():
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    @tool("system_info",
          "Data, godzina, uptime, temperatura CPU, RAM i wolne miejsce na dysku.",
          {"type": "object", "properties": {}})
    def system_info(ctx):
        info = collect_system_info()
        temp = info["cpu_temp_c"]
        temp_txt = f"{temp}°C" if temp is not None else "niedostępna"
        text = (f"Temperatura CPU: {temp_txt}. "
                f"Dysk: wolne {info['disk_free_gb']} GB z {info['disk_total_gb']} GB "
                f"({info['disk_used_pct']}% zajęte). "
                f"RAM: wolne {info['mem_available_gb']} GB z {info['mem_total_gb']} GB. "
                f"Uptime: {info['uptime']}. Czas: {info['time']}.")
        return ToolResult(text, data=info)

    @tool("read_file", "Odczyt pliku tekstowego (max 4000 znaków).",
          {"type": "object", "properties": {"path": {"type": "string"}},
           "required": ["path"]})
    def read_file(ctx, path, max_chars=4000):
        if is_sensitive_path(path):
            return ToolResult("odmowa: plik chroniony (sekrety)", ok=False)
        p = os.path.realpath(os.path.expanduser(path))
        if not os.path.isfile(p):
            return ToolResult(f"brak pliku: {path}", ok=False)
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                return ToolResult(f.read(max_chars))
        except Exception as e:
            return ToolResult(str(e), ok=False)

    @tool("list_dir", "Zawartość katalogu.",
          {"type": "object", "properties": {"path": {"type": "string"}},
           "required": ["path"]})
    def list_dir(ctx, path="."):
        if is_sensitive_path(path):
            return ToolResult("odmowa: katalog chroniony (sekrety)", ok=False)
        p = os.path.realpath(os.path.expanduser(path))
        if not os.path.isdir(p):
            return ToolResult(f"brak katalogu: {path}", ok=False)
        try:
            entries = sorted(os.listdir(p))
        except Exception as e:
            return ToolResult(str(e), ok=False)
        lines = []
        for name in entries[:500]:
            full = os.path.join(p, name)
            mark = "/" if os.path.isdir(full) else ""
            lines.append(name + mark)
        return ToolResult("\n".join(lines) or "(pusty)", data={"count": len(entries)})

    @tool("search_files", "Szukanie wzorca (regex) w plikach.",
          {"type": "object", "properties": {
              "pattern": {"type": "string"}, "path": {"type": "string"}},
           "required": ["pattern"]})
    def search_files(ctx, pattern, path=".", limit=50):
        if command_touches_secret(pattern) or is_sensitive_path(path):
            return ToolResult("odmowa: wzorzec/ścieżka chroniona", ok=False)
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return ToolResult(f"błędny regex: {e}", ok=False)
        p = os.path.realpath(os.path.expanduser(path))
        hits = []
        if os.path.isfile(p):
            files = [p]
        else:
            files = []
            for root, dirs, names in os.walk(p):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for n in names:
                    files.append(os.path.join(root, n))
        for f in files:
            if len(hits) >= limit:
                break
            if is_sensitive_path(f):
                continue
            try:
                with open(f, encoding="utf-8", errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        if rx.search(line):
                            hits.append(f"{f}:{i}: {line.strip()[:160]}")
                            if len(hits) >= limit:
                                break
            except Exception:
                continue
        return ToolResult("\n".join(hits) or "brak trafień",
                          data={"hits": len(hits)}, ok=bool(hits))

    @tool("run_command",
          "Uruchamia komendę powłoki. Odczyt (ls/df/ps/systemctl status...) od razu; "
          "komenda zmieniająca system wymaga potwierdzenia.",
          {"type": "object", "properties": {"command": {"type": "string"}},
           "required": ["command"]},
          scopes=("gated",), gate=lambda args: agent_readonly_ok(args.get("command", "")),
          confirm_text="Wykonać komendę zmieniającą system?")
    def run_command(ctx, command, timeout=120):
        command = (command or "").strip()
        if not command:
            return ToolResult("brak komendy", ok=False)
        if is_blocked_command(command):
            return ToolResult("odmowa: komenda zablokowana", ok=False)
        mirror.command(command)
        try:
            p = subprocess.run(["bash", "-lc", command], capture_output=True, text=True,
                               errors="replace", timeout=timeout,
                               cwd=os.path.expanduser("~"))
        except subprocess.TimeoutExpired:
            mirror.command(command, f"przekroczono limit {timeout}s", 124)
            return ToolResult(f"przekroczono limit {timeout}s", ok=False)
        except Exception as e:
            mirror.command(command, str(e), 1)
            return ToolResult(str(e), ok=False)
        out = (p.stdout + p.stderr).strip()[:3000]
        mirror.command(command, out, p.returncode)
        return ToolResult(out or f"(kod {p.returncode})", ok=(p.returncode == 0),
                          data={"returncode": p.returncode})

    def _sandbox_write(ctx, path, content, append):
        target = safe_write_path(path)
        if target is None:
            return ToolResult("odmowa: ścieżka systemowa chroniona", ok=False)
        ws = ctx.workspace_path(path)
        if ws is None:
            return ToolResult("odmowa: zapis tylko w piaskownicy (~/astro-agent)", ok=False)
        ws.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(ws, mode, encoding="utf-8") as f:
            f.write(content or "")
        return ToolResult(f"zapisano {len(content or '')} znaków -> {ws}", data={"path": str(ws)})

    @tool("write_file", "Zapis pliku w piaskownicy agenta.",
          {"type": "object", "properties": {
              "path": {"type": "string"}, "content": {"type": "string"}},
           "required": ["path", "content"]}, scopes=("sandbox",))
    def write_file(ctx, path, content=""):
        return _sandbox_write(ctx, path, content, append=False)

    @tool("append_file", "Dopisanie do pliku w piaskownicy agenta.",
          {"type": "object", "properties": {
              "path": {"type": "string"}, "content": {"type": "string"}},
           "required": ["path", "content"]}, scopes=("sandbox",))
    def append_file(ctx, path, content=""):
        return _sandbox_write(ctx, path, content, append=True)

    @tool("remember", "Trwały fakt o użytkowniku.",
          {"type": "object", "properties": {"text": {"type": "string"}},
           "required": ["text"]}, scopes=("sandbox",))
    def remember(ctx, text):
        if not ctx.memory:
            return ToolResult("brak pamięci", ok=False)
        ctx.memory.remember(text)
        return ToolResult(f"zapamiętane: {text}")

    @tool("ask_user", "Zadaje użytkownikowi jedno pytanie doprecyzowujące.",
          {"type": "object", "properties": {"question": {"type": "string"}},
           "required": ["question"]})
    def ask_user(ctx, question):
        return ToolResult(question, data={"ask": question})
