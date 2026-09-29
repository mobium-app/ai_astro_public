"""Offline baza wiedzy ASTRO: kuratorowane fakty, pierwsza pomoc, `learned` i FTS z knowledge.db."""

import os
import re
import sqlite3

from .. import config
from ..memory import knowledge as mem_knowledge
from .registry import ToolResult, tool

_FTS_CACHE = {"path": None, "mtime": None, "con": None}


def _fts_conn():
    path = config.KNOWLEDGE_DB
    if not path or not os.path.isfile(path):
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if _FTS_CACHE["con"] is not None and _FTS_CACHE["path"] == path \
            and _FTS_CACHE["mtime"] == mtime:
        return _FTS_CACHE["con"]
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        _FTS_CACHE.update(path=path, mtime=mtime, con=con)
        return con
    except Exception:
        return None


def search_fts(query, k=3):
    """Wyszukiwanie w technicznej bazie FTS (docs). Zwraca [(title, snippet)]."""
    con = _fts_conn()
    if con is None:
        return []
    tokens = [t for t in re.findall(r"\w+", query or "") if len(t) > 1]
    if not tokens:
        return []
    rows = []
    for match in (" ".join(tokens), " OR ".join(tokens)):
        try:
            rows = con.execute(
                "SELECT title, text FROM docs WHERE docs MATCH ? LIMIT ?", (match, k)).fetchall()
        except Exception:
            rows = []
        if rows:
            break
    out = []
    apt_q = bool(re.search(r"apt|pakiet|package|dpkg|deb", query or "", re.I))
    for r in rows:
        title = r["title"] or ""
        text = re.sub(r"\s+", " ", (r["text"] or "")).strip()
        if not apt_q and (text.startswith("Package:") or title.endswith("apt-packages")):
            continue
        out.append((title, text[:400]))
    return out


def search_all(memory, query, k=3):
    """Scalone wyniki: fakty kuratorowane, pierwsza pomoc, learned i FTS techniczny."""
    parts = []
    facts = mem_knowledge.offline_facts_answer(query)
    if facts:
        parts.append(("fakt", facts))
    aid = mem_knowledge.first_aid_reply(query)
    if aid:
        parts.append(("pierwsza pomoc", aid))
    if memory is not None:
        try:
            for text in memory.search_learned(query, k=k):
                parts.append(("learned", text))
        except Exception:
            pass
    for title, text in search_fts(query, k=k):
        parts.append((f"docs:{title}", text))
    return parts


def register():
    @tool("search_knowledge",
          "Offline baza wiedzy ASTRO: fakty, pierwsza pomoc, learned i dokumentacja techniczna.",
          {"type": "object", "properties": {"query": {"type": "string"}},
           "required": ["query"]})
    def search_knowledge(ctx, query):
        parts = search_all(ctx.memory, query, k=3)
        if not parts:
            return ToolResult("brak trafień w bazie wiedzy", ok=False)
        lines = [f"- [{src}] {text}" for src, text in parts[:6]]
        return ToolResult("\n".join(lines), data={"hits": len(parts)})

    @tool("knowledge_stats", "Statystyki offline bazy wiedzy ASTRO.",
          {"type": "object", "properties": {}})
    def knowledge_stats(ctx):
        learned = ctx.memory.learned_count() if ctx.memory else 0
        fts = 0
        con = _fts_conn()
        if con is not None:
            try:
                fts = con.execute("SELECT COUNT(*) c FROM docs").fetchone()["c"]
            except Exception:
                fts = 0
        return ToolResult(f"Wiedza ASTRO: learned={learned}, docs(FTS)={fts}, "
                          f"knowledge.db={config.KNOWLEDGE_DB}")
