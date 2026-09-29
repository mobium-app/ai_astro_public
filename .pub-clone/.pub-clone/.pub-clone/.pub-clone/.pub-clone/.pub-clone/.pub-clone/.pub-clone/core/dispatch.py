"""Dyspozycja: potwierdzenia -> WiFi -> fast-tools -> skille -> agent -> plan (+ zdalna logika)."""

import re
from dataclasses import dataclass

from .. import config, remote_support, wifi
from .. import log as astro_log
from ..safety import (assess_user_request, classify_request, is_executable_command,
                      normalize_facts)
from ..skills import match_skill, run_skill
from . import (affect_flow, compassion_flow, fast_tools, humor_flow, initiative, must_have, pending,
               planner, persona_flow, profiling, usage)
from .continuation import rewrite_continuation

# Zdalne AI dostaje WYŁĄCZNIE pytania o logikę/wiedzę (nigdy zlecenia komend — halucynuje
# wykonanie). Odpowiedź jest od razu zapisywana do `learned` (offline na przyszłość).
REMOTE_LEARN_PROMPT = (
    "Jesteś ekspertem wspierającym lokalnego agenta ASTRO. Odpowiedz rzeczowo i po polsku, "
    "pełnymi zdaniami. NIE podawaj komend systemowych ani nie twierdź, że coś wykonałaś - "
    "tylko wyjaśnij zagadnienie. Odpowiedź ma być zwięzła (do 5 zdań) i nadawać się do "
    "zapamiętania jako fakt.")
_WEAK_FRAGMENTS = ("nie udało", "nie rozumiem", "nie wiem", "przepraszam", "nie potrafię",
                   "nie jestem pewna", "błąd")


def _weak_reply(text):
    t = (text or "").strip().lower()
    if not t or len(t) < 20:
        return True
    return any(w in t for w in _WEAK_FRAGMENTS)


def _record_unknown(agent, text):
    """Zapamiętuje pytanie, na które nie umieliśmy odpowiedzieć (pętla samodoskonalenia).

    Trafia do tabeli `unknowns`; `scripts/remote_knowledge.py --unknowns` douczy je później
    (nauczyciel: bielik/darmowe) i usuwa z kolejki. Cicho pomija brak pamięci."""
    memory = getattr(agent, "memory", None)
    if memory is None or not text:
        return
    try:
        memory.record_unknown(text.strip())
    except Exception:
        pass


def _history(agent):
    """Ostatnie tury użytkownika z etykietą SWITCH-a (kontekst dla krótkich kontynuacji)."""
    memory = getattr(agent, "memory", None)
    if not memory:
        return None
    try:
        rows = memory.conversations(8)
    except Exception:
        return None
    out = []
    for row in rows:
        text = (row or {}).get("text") if isinstance(row, dict) else None
        if row.get("role") in ("user", "ty") and text:
            out.append({"text": text, "label": classify_request(text)})
    return out or None


def _remote_logic_fallback(text, agent, history=None):
    """Ostatnia deska ratunku: pytanie o logikę/wiedzę -> remote, odpowiedź zapisana do `learned`."""
    if not remote_support.available():
        return None
    # Twarda zasada: KOMENDY WYKONYWALNE nigdy nie idą do remote (model zdalny „opowiada
    # teorie" zamiast wykonać). Rozstrzyga SWITCH `safety.intent` (z kontekstem tur).
    if classify_request(text, history=history) != "question":
        return None
    if is_executable_command(text):
        return None
    low = normalize_facts(text or "")
    if fast_tools.INFO_RE.search(low) or fast_tools.NPU_RE.search(low):
        return None  # dane systemowe mamy lokalnie (narzędzia) - nie pytamy chmury
    if fast_tools.POWER_SHUTDOWN_RE.search(low) or fast_tools.POWER_REBOOT_RE.search(low):
        return None
    messages = [{"role": "system", "content": REMOTE_LEARN_PROMPT},
                {"role": "user", "content": text}]
    result = remote_support.ask(messages, tools=None, max_tokens=500, temperature=0.2)
    if not result:
        return None
    answer, label, _usage = result
    remote_support.learn_from_remote(getattr(agent, "memory", None), text, answer,
                                     source=f"remote:{label}")
    return answer


@dataclass
class DispatchResult:
    reply: str
    route: str
    agent_result: object = None


def _resolve_continuation(text, agent):
    """P3: krótką kontynuację („a jak bardzo?") scal z poprzednią wypowiedzią użytkownika.

    Dzięki temu router/klasyfikator i model widzą samodzielne pytanie, a nie urwany fragment.
    Nie rusza wypowiedzi, które mają własny temat. Zwraca tekst do dalszej obróbki."""
    if not config.SESSION_ENABLED or not fast_tools.is_followup(text):
        return text
    sess = getattr(agent, "session", None)
    if sess is None:
        return text
    prev = ""
    for turn in reversed(getattr(sess, "turns", []) or []):
        if turn.get("user"):
            prev = turn["user"]
            break
    if not prev:
        return text
    rewritten = rewrite_continuation(text, prev, fast_tools.FOLLOWUP_LEAD)
    if rewritten:
        try:
            astro_log.get_logger("dispatch").debug("kontynuacja: %r -> %r", text, rewritten)
        except Exception:
            pass
        return rewritten
    return text


def dispatch(text, agent, use_plan=False):
    # Prefiks kanału (must-have 2026-09-27): `terminal`/`czat`/`skrypt` jawnie nadpisuje routing.
    from . import prefix
    channel, body = prefix.parse(text)
    resolved = _resolve_continuation(body, agent)
    result = _dispatch(resolved, agent, use_plan, channel=channel)
    # Ostrzeżenie o ryzykownej (nieodwracalnej) operacji — doklej przed odpowiedzią.
    note = getattr(getattr(agent, "ctx", None), "risk_note", None)
    if note:
        result.reply = f"{note} {result.reply}".strip()
        agent.ctx.risk_note = None
    # Jasna instrukcja dla użytkownika, gdy czekamy na zgodę (Potwierdź / Anuluj).
    if pending.has_pending(agent) and "anuluj" not in (result.reply or "").lower():
        result.reply = f"{result.reply} {pending.CONFIRM_HINT}".strip()
    # Pamięć robocza rozmowy (P1): zapis tury dla KAŻDEJ trasy (nie tylko agent.run), by
    # krótkie kontynuacje miały kontekst. Do historii trafia odpowiedź bez podpowiedzi
    # potwierdzenia (ta dotyczy tylko bieżącej tury).
    sess = getattr(agent, "session", None)
    if sess is not None:
        try:
            reply = result.reply or ""
            if reply.endswith(pending.CONFIRM_HINT):
                reply = reply[:-len(pending.CONFIRM_HINT)].strip()
            sess.record(text, reply)
        except Exception:
            pass
    try:
        usage.log_usage(text, result)
    except Exception:
        pass
    return result


def _wifi_dispatch(wi, agent):
    """Deterministyczna obsługa Wi-Fi (offline). Zwraca DispatchResult albo None."""
    action = (wi or {}).get("action")
    if action == "scan":
        return DispatchResult(wifi.scan_text(), "wifi-scan")
    if action == "disconnect":
        _ok, msg = wifi.disconnect(wi.get("name", ""))
        return DispatchResult(msg, "wifi")
    if action == "connect":
        raw = wi.get("ssid", "")
        ssid = wifi.resolve(raw)
        if not ssid:
            return DispatchResult(f"nie znalazłam sieci {raw} w zasięgu", "wifi")
        pw = wi.get("password")
        if pw:
            from ..spelling import parse_spelled_secret
            pw = parse_spelled_secret(pw) or pw
            _ok, msg = wifi.connect(ssid, pw)
            return DispatchResult(msg, "wifi")
        if wifi.is_secured(ssid):
            setattr(agent.ctx, "wifi_pending", {"ssid": ssid})
            return DispatchResult("sieć zabezpieczona. podaj hasło", "wifi-password")
        _ok, msg = wifi.connect(ssid)
        return DispatchResult(msg, "wifi")
    return None


def _dispatch_wifi_password(text, agent):
    """Tura po „podaj hasło" (tryb tekstowy/API): dekoduje literowanie i łączy."""
    state = getattr(agent.ctx, "wifi_pending", None)
    if not state:
        return None
    norm = normalize_facts(text or "")
    if re.search(r"\b(anuluj|przerwij|stop|rezygnuje|zrezygnuj)\b", norm):
        agent.ctx.wifi_pending = None
        return DispatchResult("anulowałam łączenie z Wi-Fi", "wifi-cancel")
    from ..spelling import parse_spelled_secret
    pw = parse_spelled_secret(text)
    ssid = state.get("ssid")
    agent.ctx.wifi_pending = None
    if not pw:
        return DispatchResult("nie rozpoznałam hasła - spróbuj literować ponownie", "wifi")
    _ok, msg = wifi.connect(ssid, pw)
    return DispatchResult(msg, "wifi")


def _script_result(text, agent):
    """Prefiks `skrypt`: TYLKO deterministyczne skrypty (must-have/Wi-Fi/fast/skille). None gdy brak."""
    mh = must_have.handle(text, agent)
    if mh:
        return DispatchResult(mh[0], mh[1])
    wi = wifi.intent(text)
    if wi:
        res = _wifi_dispatch(wi, agent)
        if res:
            return res
    fast = fast_tools.try_fast(text, agent.ctx)
    if fast:
        return DispatchResult(fast, "fast")
    matched = match_skill(text)
    if matched:
        skill, params = matched
        skill_text, _ok, is_pending = run_skill(agent.ctx, skill, params)
        return DispatchResult(skill_text, "skill-confirm" if is_pending else "skill")
    return None


def _chat_result(text, agent):
    """Prefiks `czat`: rozmowa/wiedza (nigdy wykonanie). Bezpieczeństwo i RAG/remote bez zmian."""
    crisis = compassion_flow.handle(text, agent)
    if crisis:
        return DispatchResult(crisis[0], crisis[1])
    verdict, note = assess_user_request(text)
    if verdict == "refuse":
        return DispatchResult(note, "refuse")
    if verdict == "warn" and note:
        agent.ctx.risk_note = note
    for handler in (profiling.handle, persona_flow.handle, affect_flow.handle, humor_flow.handle):
        try:
            res = handler(text, agent)
        except Exception:
            res = None
        if res:
            return DispatchResult(res[0], res[1])
    result = agent.run(text, force_chat=True)
    if not result.used_tools and (_weak_reply(result.reply)
                                  or fast_tools.REASON_RE.search(normalize_facts(text or ""))):
        remote = _remote_logic_fallback(text, agent, history=_history(agent))
        if remote:
            return DispatchResult(remote, "remote-learn", result)
    if (not result.used_tools and classify_request(text) == "question"
            and _weak_reply(result.reply)):
        _record_unknown(agent, text)
    return DispatchResult(result.reply, result.route, result)


def _dispatch(text, agent, use_plan=False, channel=""):
    from . import prefix
    handled, reply, route = pending.resolve_pending(text, agent)
    if handled:
        return DispatchResult(reply, route)

    # Prefiks `czat`: rozmowa/wiedza — pomijamy WSZYSTKIE ścieżki wykonawcze.
    if channel == prefix.CZAT:
        return _chat_result(text, agent)
    # Prefiks `skrypt`: tylko przygotowane skrypty; brak trafienia = jawna odmowa (bez modelu).
    if channel == prefix.SKRYPT:
        res = _script_result(text, agent)
        if res:
            return res
        return DispatchResult("Nie mam gotowego skryptu na to polecenie. Powiedz na przykład "
                              "„skrypt znajdź dostępne sieci” albo „skrypt oblicz dwa dodać dwa”.",
                              "skrypt-miss")
    # Prefiks `skajnet`: sekcja SKAJNET listy must-have — zadania wykonywane na Pi4-SKYNET
    # (doker, zasoby, aktualizacje, temperatura, zasilanie). Determinizm, bez modelu.
    if channel == prefix.SKAJNET:
        from . import skynet
        res = skynet.handle(text, agent)
        if res:
            return DispatchResult(res[0], res[1])
        return DispatchResult("Nie mam komendy Skajnet na to polecenie. Spróbuj na przykład "
                              "„skajnet status doker” albo „skajnet pokaż zasoby systemowe”.",
                              "skajnet-miss")

    # Bezpieczeństwo: sygnały kryzysu obsługujemy z najwyższym priorytetem.
    crisis = compassion_flow.handle(text, agent)
    if crisis:
        return DispatchResult(crisis[0], crisis[1])

    # Twarda odmowa dla żądań niszczących/niebezpiecznych (deterministyczna, przed modelem).
    verdict, note = assess_user_request(text)
    if verdict == "refuse":
        return DispatchResult(note, "refuse")
    if verdict == "warn" and note:
        agent.ctx.risk_note = note

    prof = profiling.handle(text, agent)
    if prof:
        return DispatchResult(prof[0], prof[1])

    pers = persona_flow.handle(text, agent)
    if pers:
        return DispatchResult(pers[0], pers[1])

    mood = affect_flow.handle(text, agent)
    if mood:
        return DispatchResult(mood[0], mood[1])

    joke = humor_flow.handle(text, agent)
    if joke:
        return DispatchResult(joke[0], joke[1])

    # Proaktywność: tryb cichy / powrót do rozmowy (deterministyczne, przed must-have).
    ini = initiative.handle_command(text, agent)
    if ini:
        return DispatchResult(ini[0], ini[1])

    # Komendy must-have (lista /etc/astro-secrets/komendy_must-have): deterministyczne, głosowe,
    # bez modelu. Wołane PRZED Wi-Fi i fast-tools, by np. „zasoby zdalne" nie trafiło w „zasoby".
    mh = must_have.handle(text, agent)
    if mh:
        return DispatchResult(mh[0], mh[1])

    # Wi-Fi: najpierw tryb oczekiwania na hasło, potem rozpoznanie intencji.
    if getattr(agent.ctx, "wifi_pending", None) and not wifi.intent(text):
        res = _dispatch_wifi_password(text, agent)
        if res:
            return res
    wi = wifi.intent(text)
    if wi:
        res = _wifi_dispatch(wi, agent)
        if res:
            return res

    fast = fast_tools.try_fast(text, agent.ctx)
    if fast:
        return DispatchResult(fast, "fast")

    # Skille/receptury to precyzyjne, deterministyczne przepisy — uruchamiamy je także dla wypowiedzi
    # zaczynających się od słowa pytającego („ile jest wolnego miejsca", „kto jest zalogowany",
    # „co się zmieniło w ~/x"), bo to realne komendy, a nie pytania do modelu.
    matched = match_skill(text)
    if matched:
        skill, params = matched
        skill_text, _ok, is_pending = run_skill(agent.ctx, skill, params)
        if is_pending:
            return DispatchResult(skill_text, "skill-confirm")
        return DispatchResult(skill_text, "skill")

    result = agent.run(text)
    # Ostatnia deska ratunku: lokalny agent nie poradził sobie z pytaniem o logikę/wiedzę.
    # Komendy (także krótkie kontynuacje rozpoznane z kontekstu) NIGDY nie idą do remote.
    if not result.used_tools and (_weak_reply(result.reply)
                                  or fast_tools.REASON_RE.search(normalize_facts(text or ""))):
        remote = _remote_logic_fallback(text, agent, history=_history(agent))
        if remote:
            return DispatchResult(remote, "remote-learn", result)
    if use_plan and not result.used_tools and getattr(result, "route", "") == "agent":
        memory = getattr(agent, "memory", None)
        cached = memory.find_plan(text, reuse=0.90) if memory else None
        if cached:
            steps, problem = planner.safe_plan(text, cached.get("steps") or [])
            if steps:
                return DispatchResult("Plan: " + "; ".join(s["command"] for s in steps),
                                      "plan-cache", result)
        hint = None
        if memory:
            near = memory.find_plan(text, reuse=0.72)
            if near and near.get("steps"):
                hint = "; ".join(s.get("command", "") for s in near["steps"])
        steps = planner.goal_to_steps(text, agent.backends, hint=hint)
        steps, problem = planner.safe_plan(text, steps)
        if steps:
            return DispatchResult("Plan: " + "; ".join(s["command"] for s in steps),
                                  "plan", result)
        if problem:
            return DispatchResult(problem, "plan-rejected", result)
    # Nie odpowiedzieliśmy na pytanie (słaba odpowiedź, remote nie pomógł/nieosiągalny) —
    # zapisz do `unknowns`, by douczyć online później (pętla samodoskonalenia).
    if (not result.used_tools and classify_request(text) == "question"
            and _weak_reply(result.reply)):
        _record_unknown(agent, text)
    return DispatchResult(result.reply, result.route, result)
