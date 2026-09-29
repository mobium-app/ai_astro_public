"""Kuratorowana wiedza offline (facts.txt, first_aid.txt) + import do pamięci."""

import re

from .. import config
from ..safety import normalize_facts

_FACTS_CACHE = {}
_FIRST_AID_CACHE = {}


def _parse_facts(path):
    key = str(path)
    if key in _FACTS_CACHE:
        return _FACTS_CACHE[key]
    facts = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=>" not in line:
                    continue
                keys, ans = line.split("=>", 1)
                pats = []
                for k in keys.split(";"):
                    nk = normalize_facts(k.strip())
                    if len(nk) < 3:
                        continue
                    last = nk.split()[-1]
                    if nk[-1] in "aeiouy" and len(last) >= 3 and len(nk) - 1 >= 3:
                        nk = nk[:-1]
                    pats.append((re.compile(r"(?<!\w)" + re.escape(nk) + r"\w*"), len(nk)))
                if pats and ans.strip():
                    facts.append((keys.strip(), pats, ans.strip()))
    except Exception:
        pass
    _FACTS_CACHE[key] = facts
    return facts


def offline_facts_answer(query, path=None):
    q = normalize_facts(query)
    best, bestscore = None, (0, 0)
    for _keys, pats, ans in _parse_facts(path or config.FACTS_FILE):
        for rx, klen in pats:
            m = rx.search(q)
            if m:
                score = (klen, m.end() - m.start())
                if score > bestscore:
                    best, bestscore = ans, score
    return best


def _parse_first_aid(path):
    key = str(path)
    if key in _FIRST_AID_CACHE:
        return _FIRST_AID_CACHE[key]
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=>" not in line:
                    continue
                keys, ans = line.split("=>", 1)
                pats = []
                for k in keys.split(";"):
                    k = k.strip()
                    if not k:
                        continue
                    try:
                        pats.append(re.compile(r"(?<!\w)(?:" + k + r")", re.I))
                    except re.error:
                        continue
                if pats and ans.strip():
                    entries.append((keys.strip(), pats, ans.strip()))
    except Exception:
        pass
    _FIRST_AID_CACHE[key] = entries
    return entries


def offline_first_aid_answer(query, path=None):
    q = normalize_facts(query)
    best, bestlen = None, 0
    for _keys, pats, ans in _parse_first_aid(path or config.FIRST_AID_FILE):
        for rx in pats:
            m = rx.search(q)
            if m:
                span = m.end() - m.start()
                if span > bestlen:
                    best, bestlen = ans, span
    return best


def with_medical_disclaimer(ans):
    if not ans:
        return ans
    low = ans.lower()
    if "112" in ans or "lekarz" in low or "pogotow" in low or "dyżur" in low:
        return ans
    return ans.rstrip() + " To wskazówka, nie diagnoza - w razie wątpliwości skontaktuj się z lekarzem."


def first_aid_reply(query):
    ans = offline_first_aid_answer(query)
    if not ans:
        return None
    return with_medical_disclaimer(ans)


def import_curated(memory, facts_file=None, first_aid_file=None):
    """Importuje TYLKO kuratorowane fakty i pierwszą pomoc (bez śmieci). Zwraca licznik."""
    facts = _parse_facts(facts_file or config.FACTS_FILE)
    aid = _parse_first_aid(first_aid_file or config.FIRST_AID_FILE)
    before = memory.learned_count()
    for keys, _pats, ans in facts:
        memory.add_learned("fakt", keys, ans, source="facts", verified=True, confidence=1.0)
    for keys, _pats, ans in aid:
        memory.add_learned("first_aid", keys, ans, source="first_aid", verified=True,
                           confidence=1.0)
    return {"facts": len(facts), "first_aid": len(aid),
            "added": memory.learned_count() - before, "learned": memory.learned_count()}
