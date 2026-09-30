"""Weryfikacja odpowiedzi względem użytych narzędzi."""

import re

NEEDS_TOOLS_RE = re.compile(
    r"temperatur|dysk|wolne miejsce|ram|pami[eę]c|proces|\bip\b|uptime|throttl|"
    r"plik|katalog|folder|zawarto|system|godzin|dat[ęa]|stan|status", re.I)


def needs_tools(text):
    return bool(NEEDS_TOOLS_RE.search(text or ""))


def check(answer, used_tools, text, already_nudged=False):
    """Zwraca (ok, nudge). Nudge to komunikat dopisany do kontekstu przy kolejnej próbie."""
    if not (answer or "").strip():
        return False, "Twoja odpowiedź była pusta - odpowiedz konkretnie."
    if needs_tools(text) and not used_tools and not already_nudged:
        return False, ("To pytanie wymaga danych z systemu - użyj narzędzia (np. system_info, "
                       "read_file, run_command), nie zgaduj.")
    return True, None
