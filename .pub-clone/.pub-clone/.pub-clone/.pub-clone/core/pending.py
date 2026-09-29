"""Rozwiązywanie oczekujących akcji (Potwierdź / Anuluj) - domknięcie pętli bramek.

Wcześniej `Confirmer` zapisywał `pending`, ale nikt nie wołał `answer()`, więc ASTRO pytał
„czy potwierdzić", a „tak/potwierdzam" nic nie robiło. Tutaj dispatch sprawdza pending
na początku tury, woła `answer()` i wznawia akcję po potwierdzeniu.
"""

CANCEL_REPLY = "Anulowano."
CONFIRM_HINT = "Powiedz „potwierdzam”, aby wykonać, albo „anuluj”, aby zrezygnować."


def _confirmer(agent):
    return getattr(getattr(agent, "ctx", None), "confirmer", None)


def has_pending(agent):
    conf = _confirmer(agent)
    return bool(conf is not None and getattr(conf, "pending", None) is not None)


def resolve_pending(text, agent):
    """Zwraca (handled, reply, route). `handled=False`, gdy brak pending albo to nowe polecenie
    (wtedy pending jest czyszczony i polecenie idzie zwykłą ścieżką)."""
    conf = _confirmer(agent)
    if conf is None or getattr(conf, "pending", None) is None:
        return False, "", ""
    handled, ok, pending = conf.answer(text)
    if not handled:
        # Nowa wypowiedź (nie potwierdzenie/anulowanie) zastępuje oczekującą akcję.
        conf.clear()
        return False, "", ""
    if not ok:
        return True, CANCEL_REPLY, "confirm-cancel"
    return True, execute_pending(pending, agent), "confirm-run"


def execute_pending(pending, agent):
    """Wznawia zatwierdzoną akcję. Ustawia `assume_confirmed`, by pominąć bramkę raz."""
    kind = (pending or {}).get("kind") or ""
    payload = (pending or {}).get("payload") or {}
    ctx = getattr(agent, "ctx", None)
    if ctx is None:
        return f"Nie mogę wznowić akcji: {kind}"
    ctx.assume_confirmed = True
    try:
        if kind == "system_task":
            from ..tools.tasks import execute_steps
            steps = payload.get("steps") or []
            if not steps:
                return "Brak kroków do wykonania."
            return execute_steps(ctx, payload.get("goal") or "zadanie", steps).text
        if kind == "skill":
            from ..skills import run_skill
            text, _ok, _pending = run_skill(ctx, payload.get("skill"), payload.get("params") or {})
            return text
        reg = getattr(ctx, "registry", None)
        if reg is not None and reg.get(kind) is not None:
            return reg.execute(kind, payload, ctx).text
        return f"Nie umiem wznowić akcji: {kind}"
    finally:
        ctx.assume_confirmed = False
