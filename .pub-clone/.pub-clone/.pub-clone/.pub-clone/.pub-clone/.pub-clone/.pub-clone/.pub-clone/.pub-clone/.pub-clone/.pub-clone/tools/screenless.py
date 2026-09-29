"""Narzędzia „bez ekranu" (audio-only): sieć, aktualizacje, katalogi, zasilanie.

Priorytet: ASTRO ma obsłużyć te komendy głosem, bez monitora. Mutacje są `gated` (wymagają
potwierdzenia), odczyt (skan Wi-Fi) jest `read`. Wszystko przez argv (bez powłoki) i `sudo -n`.
"""

import os
import re
import shutil
import subprocess
import time

from .power import execute_power
from .registry import ToolResult, tool
from .. import mirror, wifi
from ..spelling import looks_spelled, parse_spelled_secret

_SSID_RE = re.compile(r"^[\w .\-'ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{1,64}$")

_UPDATE_LABELS = {
    "update": "Zaktualizować repozytoria (apt update)?",
    "upgrade": "Zaktualizować pakiety (apt upgrade)?",
    "full": "Zaktualizować programy (apt update + upgrade)?",
}


def _run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return r.returncode, out
    except subprocess.TimeoutExpired:
        return 124, f"przekroczono limit {timeout}s"
    except Exception as e:
        return 1, str(e)


def _run_stream(argv, timeout=600, chunk_s=0.8):
    """Uruchamia komendę i pokazuje NA ŻYWO jej wynik na terminalach (mirror).

    `apt` potrafi mielić kilkadziesiąt sekund - wcześniej ekran milczał do końca komendy.
    Zwraca (kod, pełny_wynik)."""
    line = " ".join(argv)
    mirror.command("sudo -n " + line, root=True)
    try:
        proc = subprocess.Popen(["sudo", "-n"] + argv, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
    except Exception as e:
        return 1, str(e)
    lines, buf, last = [], [], 0.0
    try:
        for raw in proc.stdout or ():
            raw = raw.rstrip("\n")
            if not raw.strip():
                continue
            lines.append(raw)
            buf.append(raw)
            now = time.time()
            if now - last >= chunk_s:
                mirror.wall_write("\n".join(buf))
                buf, last = [], now
        if buf:
            mirror.wall_write("\n".join(buf))
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = 124
    mirror.command(line, "", code, root=True)
    return code, "\n".join(lines)


def _cidr():
    code, out = _run(["ip", "-o", "-f", "inet", "addr", "show"], timeout=10)
    if code == 0:
        for line in out.splitlines():
            m = re.search(r"inet (\d+\.\d+\.\d+\.\d+/\d+)", line)
            if m and not m.group(1).startswith("127."):
                return m.group(1)
    return ""


def register():
    @tool("system_power", "Wyłącza lub restartuje Raspberry Pi (wymaga potwierdzenia).",
          {"type": "object",
           "properties": {"action": {"type": "string", "enum": ["shutdown", "reboot"]}},
           "required": ["action"]},
          scopes=("gated",), confirm_text="Akcja zasilania Raspberry Pi")
    def system_power(ctx, action):
        return execute_power(action)

    @tool("make_dir", "Tworzy katalog w piaskownicy agenta (~/astro-agent).",
          {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
          scopes=("sandbox",))
    def make_dir(ctx, path):
        target = ctx.workspace_path(path)
        if target is None:
            return ToolResult("odmowa: katalog tylko w piaskownicy (~/astro-agent)", ok=False)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return ToolResult(f"błąd tworzenia katalogu: {e}", ok=False)
        return ToolResult(f"utworzono katalog: {target}")

    @tool("wifi_scan", "Skanuje dostępne sieci Wi-Fi (SSID, siła, zabezpieczenia).",
          {"type": "object", "properties": {}})
    def wifi_scan(ctx):
        return ToolResult(wifi.scan_text(), ok=wifi.available())

    @tool("wifi_connect", "Łączy z siecią Wi-Fi (SSID + hasło; hasło może być literowane).",
          {"type": "object",
           "properties": {"ssid": {"type": "string"}, "password": {"type": "string"}},
           "required": ["ssid"]},
          scopes=("gated",), confirm_text="Połączyć z siecią Wi-Fi?")
    def wifi_connect(ctx, ssid, password=""):
        target = wifi.resolve(ssid) or (ssid or "").strip()
        if not _SSID_RE.match(target):
            return ToolResult(f"niepoprawna nazwa sieci: {ssid!r}", ok=False)
        if password and looks_spelled(password):
            password = parse_spelled_secret(password) or password
        if not password and wifi.is_secured(target):
            return ToolResult("sieć zabezpieczona. podaj hasło")
        ok, msg = wifi.connect(target, password or None)
        return ToolResult(msg, ok=ok)

    @tool("wifi_disconnect", "Rozłącza aktywne Wi-Fi (nazwa może być częścią SSID).",
          {"type": "object", "properties": {"name": {"type": "string"}}},
          scopes=("gated",), confirm_text="Rozłączyć z siecią Wi-Fi?")
    def wifi_disconnect(ctx, name=""):
        ok, msg = wifi.disconnect(name)
        return ToolResult(msg, ok=ok)

    @tool("network_scan", "Skanuje urządzenia w sieci lokalnej (nmap -sn).",
          {"type": "object", "properties": {"cidr": {"type": "string"}}},
          scopes=("gated",), confirm_text="Zeskanować sieć lokalną?")
    def network_scan(ctx, cidr=""):
        if not shutil.which("nmap"):
            return ToolResult("brak nmap - nie mogę skanować sieci.", ok=False)
        target = (cidr or "").strip() or _cidr()
        if not target:
            return ToolResult("nie ustaliłem zakresu sieci (podaj CIDR, np. 192.168.0.0/24)",
                              ok=False)
        code, out = _run(["sudo", "-n", "nmap", "-sn", target], timeout=180)
        if code != 0:
            code, out = _run(["nmap", "-sn", target], timeout=180)
        return ToolResult(f"Skan sieci {target}:\n{out[:1500]}", ok=(code == 0))

    @tool("update_system", "Aktualizuje repozytoria (update) lub pakiety (upgrade).",
          {"type": "object",
           "properties": {"action": {"type": "string", "enum": ["update", "upgrade", "full"]}},
           "required": ["action"]},
          scopes=("gated",), self_gated=True,
          confirm_text="Zaktualizować system (apt)?")
    def update_system(ctx, action):
        action = (action or "").strip().lower()
        cmds = {"update": [["apt-get", "-y", "update"]],
                "upgrade": [["apt-get", "-y", "upgrade"]],
                "full": [["apt-get", "-y", "update"], ["apt-get", "-y", "upgrade"]]}
        steps = cmds.get(action)
        if not steps:
            return ToolResult(f"nieznana akcja aktualizacji: {action}", ok=False)
        label = _UPDATE_LABELS.get(action, "Zaktualizować system (apt)?")
        if ctx.confirmer is not None and not getattr(ctx, "assume_confirmed", False):
            if not ctx.confirmer.require_confirm(label, "update_system", {"action": action}):
                return ToolResult(f"Wymaga potwierdzenia: {label}", ok=False,
                                  data={"pending": True, "kind": "update_system",
                                        "payload": {"action": action}})
        out = []
        for argv in steps:
            line = " ".join(argv)
            code, text = _run_stream(argv, timeout=600)
            out.append(f"$ {line} -> kod {code}\n{text[-800:]}")
            if code != 0:
                return ToolResult("aktualizacja przerwana:\n" + "\n".join(out), ok=False)
        return ToolResult("Aktualizacja zakończona:\n" + "\n".join(out))
