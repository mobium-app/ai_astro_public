"""Zasilanie Raspberry Pi: shutdown/reboot - wyłącznie za świadomym potwierdzeniem.

Narzędzie nie jest wystawiane modelowi w schemacie (poza `TOOLS_SCHEMA`). Wywołuje je
deterministyczny fast-path (`core/fast_tools.py`) albo potwierdzenie w `core/pending.py`.
"""

import subprocess

from .registry import ToolResult, tool
from .. import mirror

POWER_ACTIONS = {"shutdown": "-h", "reboot": "-r"}
POWER_LABELS = {"shutdown": "wyłączenie systemu", "reboot": "restart systemu"}


def execute_power(action):
    action = (action or "").strip().lower()
    flag = POWER_ACTIONS.get(action)
    if flag is None:
        return ToolResult(f"nieznana akcja zasilania: {action}", ok=False)
    cmd = ["sudo", "-n", "shutdown", flag, "now"]
    # Ekran ma pokazywać, co ASTRO robi (spójnie z aktualizacjami i Wi-Fi).
    mirror.command(" ".join(cmd), root=True)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=30)
    except Exception as e:
        return ToolResult(f"błąd akcji zasilania {action}: {e}", ok=False)
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    ok = p.returncode == 0
    mirror.command(" ".join(cmd), out[:400], p.returncode, root=True)
    return ToolResult(f"{action}: {'wykonano' if ok else 'błąd'} (kod {p.returncode})"
                      + (f": {out[:200]}" if out else ""), ok=ok)


def register():
    @tool("power", "Wyłącza lub restartuje Raspberry Pi (wymaga potwierdzenia użytkownika).",
          {"type": "object",
           "properties": {"action": {"type": "string", "enum": ["shutdown", "reboot"]}},
           "required": ["action"]},
          scopes=("gated",), self_gated=True,
          confirm_text="Akcja zasilania Raspberry Pi")
    def power(ctx, action):
        if ctx.confirmer is not None and not getattr(ctx, "assume_confirmed", False):
            confirmed = ctx.confirmer.require_confirm(
                f"Akcja zasilania: {action}", "power", {"action": action})
            if not confirmed:
                label = POWER_LABELS.get(action, action)
                return ToolResult(f"Wymaga potwierdzenia: {label}", ok=False,
                                  data={"pending": True, "kind": "power",
                                        "payload": {"action": action}})
        return execute_power(action)
