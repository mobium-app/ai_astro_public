"""Narzędzia systemowe: dokumentacja poleceń, walidacja i uruchamianie skryptów."""

import os
import re
import shutil
import subprocess
import sys

from ..safety import command_touches_secret
from .registry import ToolResult, tool

_CMD_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$")


def man_page_text(name, max_chars=4000):
    name = (name or "").strip().split()[0] if (name or "").strip() else ""
    if not name or not _CMD_NAME_RE.match(name):
        return "błąd: podaj nazwę polecenia (np. 'grep')"
    if command_touches_secret(name):
        return "odmowa: niedozwolone polecenie"
    try:
        r = subprocess.run(["man", "-P", "cat", name], capture_output=True, text=True,
                           errors="replace", timeout=20)
    except Exception as e:
        return f"błąd man: {e}"
    out = re.sub(r".\x08", "", (r.stdout or ""))
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    if not out:
        return f"brak strony man dla '{name}' - spróbuj cmd_help (--help)"
    return out[:max_chars]


def cmd_help_text(command, max_chars=4000):
    command = (command or "").strip().split()[0] if (command or "").strip() else ""
    if not command or not _CMD_NAME_RE.match(command):
        return "błąd: podaj nazwę polecenia (np. 'rsync')"
    if command_touches_secret(command):
        return "odmowa: niedozwolone polecenie"
    tldr = shutil.which("tldr")
    if tldr:
        try:
            r = subprocess.run([tldr, command], capture_output=True, text=True,
                               errors="replace", timeout=20)
            out = (r.stdout or "").strip()
            if r.returncode == 0 and out and "not found" not in out.lower():
                return out[:max_chars]
        except Exception:
            pass
    path = shutil.which(command)
    if not path:
        return f"nie znaleziono polecenia '{command}'"
    if not any(path.startswith(p) for p in ("/usr/bin/", "/bin/", "/usr/sbin/", "/sbin/")):
        return "odmowa: tylko polecenia systemowe"
    for flag in ("--help", "-h"):
        try:
            r = subprocess.run([path, flag], capture_output=True, text=True, errors="replace",
                               timeout=10)
        except Exception as e:
            return f"błąd: {e}"
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if out:
            return out[:max_chars]
    return f"brak pomocy dla '{command}'"


def check_script_text(path, max_chars=3000):
    path = os.path.expanduser(path or "")
    if not os.path.isfile(path):
        return False, "brak pliku"
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, errors="replace") as f:
            head = f.read(200)
    except Exception as e:
        return False, f"błąd odczytu: {e}"
    if ext == ".py" or (not ext and head.startswith("#!") and "python" in head.split("\n", 1)[0]):
        try:
            r = subprocess.run([sys.executable, "-m", "py_compile", path], capture_output=True,
                               text=True, errors="replace", timeout=30)
        except Exception as e:
            return False, f"py_compile błąd: {e}"
        if r.returncode != 0:
            return False, "BŁĄD składni:\n" + ((r.stderr or r.stdout or "")[:max_chars])
        pf = shutil.which("pyflakes")
        if pf:
            try:
                r2 = subprocess.run([pf, path], capture_output=True, text=True,
                                    errors="replace", timeout=30)
                w = ((r2.stdout or "") + (r2.stderr or "")).strip()
                if w:
                    return True, "pyflakes (ostrzeżenia, nie blokują):\n" + w[:max_chars]
            except Exception:
                pass
        return True, "OK: py_compile bez błędów"
    if ext in (".sh", ".bash") or head.startswith("#!"):
        sc = shutil.which("shellcheck")
        if not sc:
            try:
                r = subprocess.run(["bash", "-n", path], capture_output=True, text=True,
                                   errors="replace", timeout=30)
                if r.returncode != 0:
                    return False, "BŁĄD składni bash:\n" + ((r.stderr or "")[:max_chars])
                return True, "OK: bash -n bez błędów (shellcheck niedostępny)"
            except Exception as e:
                return True, f"walidacja pominięta: {e}"
        try:
            r = subprocess.run([sc, "-S", "warning", path], capture_output=True, text=True,
                               errors="replace", timeout=30)
        except Exception as e:
            return True, f"shellcheck błąd uruchomienia: {e}"
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return (r.returncode == 0), (out[:max_chars] if out else "OK: shellcheck bez uwag")
    return True, "nieznany typ skryptu - pomijam walidację"


def run_script_text(ctx, path, timeout=120):
    ws = ctx.workspace_path(path)
    if ws is None or not ws.is_file():
        return 1, "brak skryptu w piaskownicy (~/astro-agent)"
    try:
        r = subprocess.run(["bash", str(ws)], capture_output=True, text=True, errors="replace",
                           timeout=timeout, cwd=str(ws.parent))
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"przekroczono limit {timeout}s"
    except Exception as e:
        return 1, str(e)


def register():
    @tool("man_page", "Strona man polecenia (tekst).",
          {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]})
    def man_page(ctx, name):
        out = man_page_text(name)
        return ToolResult(out, ok=not out.startswith(("błąd", "brak", "odmowa")))

    @tool("cmd_help", "Pomoc polecenia (tldr albo --help/-h).",
          {"type": "object", "properties": {"command": {"type": "string"}},
           "required": ["command"]})
    def cmd_help(ctx, command):
        out = cmd_help_text(command)
        return ToolResult(out, ok=not out.startswith(("błąd", "brak", "odmowa", "nie znaleziono")))

    @tool("check_script", "Waliduje skrypt (bash -n/shellcheck, py_compile/pyflakes).",
          {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})
    def check_script(ctx, path):
        p = os.path.expanduser(path or "")
        candidate = p if os.path.isfile(p) else None
        if candidate is None:
            safe = ctx.workspace_path(path)
            candidate = str(safe) if safe else p
        ok, desc = check_script_text(candidate)
        return ToolResult(desc, ok=ok)

    @tool("npu_status", "Stan NPU Hailo-10H: urządzenie, HEF, silniki i telemetria aplikacyjna.",
          {"type": "object", "properties": {}})
    def npu_status(ctx):
        from ..backends import npu_status_text
        return ToolResult(npu_status_text())

    @tool("run_script", "Uruchamia skrypt z piaskownicy agenta (wymaga potwierdzenia).",
          {"type": "object", "properties": {
              "path": {"type": "string"}, "timeout": {"type": "integer"}},
           "required": ["path"]},
          scopes=("gated", "sandbox"), confirm_text="Uruchomić skrypt z piaskownicy?")
    def run_script(ctx, path, timeout=120):
        code, out = run_script_text(ctx, path, timeout=timeout)
        return ToolResult(f"kod {code}: {out or '(brak wyjścia)'}", ok=(code == 0),
                          data={"returncode": code})
