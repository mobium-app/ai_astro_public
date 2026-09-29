"""Warstwa bezpieczeństwa: decyzje 'wolno/nie' + potwierdzenia. Nie zna modeli."""

from .normalize import (
    assess_user_request,
    check_request,
    classify_request,
    clarify_question,
    is_correction,
    is_system_action,
    is_unhandled_action,
    looks_like_failure,
    normalize_command,
    normalize_facts,
    normalize_text,
    SYSTEM_ACTION,
)
from .intent import classify_intent, is_executable_command
from .secrets import (
    SECRET_HINTS,
    SECRET_PATHS,
    command_touches_secret,
    is_private_url,
    is_sensitive_path,
)
from .commands import (
    AGENT_BAD_FLAGS,
    AGENT_READONLY_CMD,
    AGENT_UNSAFE_OPS,
    BLOCKED_COMMANDS,
    BLOCKED_WRITE_PREFIXES,
    CANCEL_RE,
    CANCEL_WORDS,
    CONFIRM_ONLY_RE,
    CONFIRM_RE,
    CONFIRM_SHORT_RE,
    CONFIRM_WORDS,
    DANGEROUS_CMD,
    SAFE_CMD_RE,
    SHELL_META_RE,
    agent_readonly_ok,
    is_blocked_command,
    is_safe_command,
    safe_write_path,
)
from .plans import already_installed, validate_plan
from .confirm import Confirmer, is_confirmation, is_confirm_like

DEFAULT_CONFIRMER = Confirmer()


def require_confirm(announce, kind, payload=None):
    return DEFAULT_CONFIRMER.require_confirm(announce, kind, payload)


def classify(text):
    return classify_request(text)


__all__ = [
    "assess_user_request", "check_request", "classify", "classify_request", "clarify_question",
    "classify_intent", "is_executable_command",
    "is_correction", "is_system_action", "is_unhandled_action", "looks_like_failure",
    "normalize_facts", "normalize_text", "normalize_command", "SYSTEM_ACTION",
    "SECRET_HINTS", "SECRET_PATHS", "command_touches_secret", "is_private_url",
    "is_sensitive_path",
    "AGENT_BAD_FLAGS", "AGENT_READONLY_CMD", "AGENT_UNSAFE_OPS", "BLOCKED_COMMANDS",
    "BLOCKED_WRITE_PREFIXES",     "CANCEL_RE", "CANCEL_WORDS", "CONFIRM_ONLY_RE", "CONFIRM_RE", "CONFIRM_SHORT_RE",
    "CONFIRM_WORDS", "DANGEROUS_CMD", "SAFE_CMD_RE", "SHELL_META_RE", "agent_readonly_ok",
    "is_blocked_command", "is_safe_command", "safe_write_path",
    "already_installed", "validate_plan", "Confirmer", "DEFAULT_CONFIRMER", "require_confirm",
    "is_confirm_like", "is_confirmation",
]
