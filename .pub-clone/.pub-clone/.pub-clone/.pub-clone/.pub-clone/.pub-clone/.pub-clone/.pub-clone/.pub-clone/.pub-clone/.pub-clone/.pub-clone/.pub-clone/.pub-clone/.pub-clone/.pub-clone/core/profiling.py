"""Deterministyczna obsługa profilu w dispatch: „poznaj mnie", „co o mnie wiesz", „zapomnij".

Bez modelu i bez sieci. Wywiad i dane osobowe (adres) nigdy nie opuszczają urządzenia.
"""

import re

from .. import mirror, wifi
from ..safety import normalize_command, normalize_facts
from ..user import profile as P
from ..user.intake import ProfileIntake, is_confirm
from . import fast_tools, must_have

TRIGGER_RE = re.compile(
    r"\bpoznaj\w*\s+mnie\b|\bpoznajmy\s+si[eę]\b|\bpoznajmy\b|\bpoznajemy\b|"
    r"\bzbieraj\s+dane\b|\bzbierz\s+dane\b|\bzacznij\s+zbierac\s+dane\b|"
    r"\buzupe[lł]nij\s+(?:dane|informacje|profil)\b|\bwyp[eę]lnij\s+(?:dane|profil)\b|"
    r"\bustaw\s+(?:moj\s+|m[oó]j\s+)?profil\b|\bwyp[eę]lnij\s+profil\b|\buzupe[lł]nij\s+profil\b")
QUERY_RE = re.compile(
    r"\bco o mnie wiesz\b|\bco wiesz o mnie\b|\bpoka[zż]\s+(?:moj\s+|m[oó]j\s+)?profil\b|"
    r"\bmoj\s+profil\b|\bm[oó]j\s+profil\b|\bkim jestem\b|\bco masz o mnie\b")
FORGET_RE = re.compile(
    r"\bzapomnij\s+(?:o\s+)?mnie\b|\bzapomnij\s+wszystko\b|"
    r"\busu[nń]\s+(?:moj\s+|m[oó]j\s+)?profil\b|"
    r"\bwykasuj\s+profil\b|\bskasuj\s+profil\b")


def _store(agent):
    memory = getattr(agent, "memory", None) or getattr(
        getattr(agent, "ctx", None), "memory", None)
    return getattr(memory, "profiles", None) if memory is not None else None


def handle(text, agent):
    """Zwraca (reply, route) albo None, gdy to nie dotyczy profilu."""
    ctx = getattr(agent, "ctx", None)
    store = _store(agent)
    if ctx is None or store is None:
        return None
    norm = normalize_facts(text or "")

    if getattr(ctx, "profile_intake", None) is not None:
        intake = ctx.profile_intake
        # Powtórzone „poznaj mnie" w trakcie wywiadu = powtórz bieżące pytanie. Wcześniej takie
        # powtórzenie było zapisywane jako odpowiedź (imię „Poznaj mnie") i wywiad się rozjeżdżał.
        if TRIGGER_RE.search(norm):
            return intake.repeat(), "profile-intake"
        # „zapomnij o mnie" przerywa wywiad i przechodzi do potwierdzenia usunięcia profilu.
        if FORGET_RE.search(norm):
            intake.cancelled = True
            ctx.profile_intake = None
            ctx.profile_forget_pending = True
            return "Na pewno? Powiedz potwierdzam, aby usunąć cały profil.", "profile-forget-ask"
        # „co o mnie wiesz" w trakcie wywiadu: odpowiedz i wróć do bieżącego pytania.
        if QUERY_RE.search(norm):
            lines = P.summary_lines(store.get(), masked=True)
            base = ("Wiem o Tobie tyle:\n" + "\n".join(lines) if lines
                    else "Nie znam jeszcze Twojego profilu.")
            return base + "\nWróćmy do wywiadu. " + intake.repeat(), "profile"
        # Komendy deterministyczne (must-have/Wi-Fi/szybkie) mają pierwszeństwo nad wywiadem —
        # lista must-have wymaga, by działały ZAWSZE. Wywiad zostaje aktywny.
        if _global_command(text):
            return None
        reply = intake.feed(text)
        _sync(intake.answers)
        if intake.active:
            return reply, "profile-intake"
        ctx.profile_intake = None
        if intake.cancelled:
            return reply, "profile-cancel"
        if intake.answers:
            store.replace(intake.answers, source="intake")
        return reply + " " + _spoken(store.get()), "profile"

    if getattr(ctx, "profile_forget_pending", False):
        ctx.profile_forget_pending = False
        if is_confirm(text):
            store.forget()
            return "Zapomniałam Twój profil.", "profile-forget"
        return "Dobrze, zostawiam profil bez zmian.", "profile-forget-cancel"

    if FORGET_RE.search(norm):
        ctx.profile_forget_pending = True
        return "Na pewno? Powiedz potwierdzam, aby usunąć cały profil.", "profile-forget-ask"

    if QUERY_RE.search(norm):
        lines = P.summary_lines(store.get(), masked=True)
        if not lines:
            return "Nie znam jeszcze Twojego profilu. Powiedz poznaj mnie.", "profile"
        return "Wiem o Tobie tyle:\n" + "\n".join(lines), "profile"

    if TRIGGER_RE.search(norm):
        existing = store.get()
        intake = ProfileIntake(existing)
        ctx.profile_intake = intake
        return intake.start(), "profile-intake"

    return None


def _global_command(text):
    """True, gdy wypowiedź to znana komenda deterministyczna (priorytet nad wywiadem).

    Ten sam zestaw, który `audio/loop.py:_known_score` uznaje za konkretną intencję — dzięki
    temu komendy głosowe (głośność, Wi-Fi, zasoby, czas, zasilanie...) nie giną w wywiadzie.
    """
    if not text:
        return False
    if must_have.intent(text) or wifi.intent(text):
        return True
    low = normalize_command(text)
    if (fast_tools.TIME_RE.search(low) or fast_tools.DATE_RE.search(low)
            or fast_tools.REPORT_RE.search(low) or fast_tools.RESOURCE_RE.search(low)
            or fast_tools.UPDATE_STATUS_RE.search(low) or fast_tools.WEATHER_RE.search(low)
            or fast_tools.VOLUME_RE.search(low) or fast_tools.SERVICE_RE.search(low)
            or fast_tools.update_action(low)):
        return True
    if fast_tools.POWER_NEG_RE.search(low):
        return False
    return bool(fast_tools.POWER_SHUTDOWN_RE.search(low)
                or fast_tools.POWER_REBOOT_RE.search(low))


def _sync(values):
    try:
        mirror.set_redactions(P.private_values(values or {}))
    except Exception:
        pass


def _spoken(profile):
    sal = P.salutation(profile)
    return f"Miło mi, {sal}." if sal else ""
