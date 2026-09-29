"""Pamięć ASTRO: nowy memory.db (epizody, lekcje, CBR, wiedza, unknowns) + wektory."""

import collections
import json
import re
import sqlite3
import time
from pathlib import Path

from .. import config
from ..safety import normalize_facts
from . import biocrypto

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY, ts REAL, text TEXT, embedding BLOB);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY, ts REAL, role TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS session_turns (
    id INTEGER PRIMARY KEY, ts REAL, user TEXT, assistant TEXT);
CREATE TABLE IF NOT EXISTS session_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1), summary TEXT, last_ts REAL);
CREATE TABLE IF NOT EXISTS context_digests (
    day TEXT PRIMARY KEY, summary TEXT, turns INTEGER DEFAULT 0, ts REAL);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY, ts REAL, text TEXT, last REAL, hits INTEGER DEFAULT 0,
    polarity TEXT DEFAULT 'neutral');
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY, ts REAL, last REAL, goal TEXT, embedding BLOB,
    steps_json TEXT, ok INTEGER DEFAULT 0, fail INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS trajectories (
    id INTEGER PRIMARY KEY, ts REAL, kind TEXT, goal TEXT, steps_json TEXT,
    result TEXT, answer TEXT, source TEXT, ok INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS trajectory_vectors (
    trajectory_id INTEGER PRIMARY KEY, embedding BLOB);
CREATE TABLE IF NOT EXISTS learned (
    id INTEGER PRIMARY KEY, ts REAL, topic TEXT, title TEXT, text TEXT,
    source TEXT, verified INTEGER DEFAULT 0, confidence REAL DEFAULT 0.5, url TEXT, qkey TEXT);
CREATE TABLE IF NOT EXISTS learned_vectors (
    learned_id INTEGER PRIMARY KEY, embedding BLOB);
CREATE TABLE IF NOT EXISTS unknowns (
    id INTEGER PRIMARY KEY, ts REAL, text TEXT, hits INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS faces (
    id INTEGER PRIMARY KEY, ts REAL, name TEXT, embedding BLOB, count INTEGER DEFAULT 1,
    last REAL, source TEXT);
CREATE TABLE IF NOT EXISTS bodies (
    id INTEGER PRIMARY KEY, ts REAL, name TEXT, embedding BLOB, count INTEGER DEFAULT 1,
    last REAL, source TEXT);
CREATE TABLE IF NOT EXISTS face_sightings (
    id INTEGER PRIMARY KEY, ts REAL, name TEXT, score REAL, known INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS vision_notes (
    id INTEGER PRIMARY KEY, ts REAL, kind TEXT, text TEXT);
"""


def _pack_emb(vec, encrypt=True):
    """float32[] -> BLOB. Domyślnie szyfrowany (dane biometryczne); `encrypt=False` jawnie."""
    import array
    raw = array.array("f", [float(x) for x in vec]).tobytes()
    return biocrypto.encrypt(raw) if encrypt else raw


def normalize_name(name):
    """Ujednolica imię osoby: `kasia` -> `Kasia` (pierwsza litera wielka).

    Osoby (twarze/sylwetki) są kluczowane po imieniu, więc „Kasia" i „kasia" to ta sama osoba;
    bez normalizacji powstawały duplikaty (zaobserwowane 2026-09-28).
    """
    n = (name or "").strip()
    return n[:1].upper() + n[1:] if n else ""


def _unpack_emb(blob):
    import array
    a = array.array("f")
    a.frombytes(biocrypto.decrypt(blob) or b"")
    return a.tolist()


def _cosine(a, b):
    import math
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0

# Bramka jakości wpisów `learned` (remote/web/factory): odrzuca szum, zanim trafi do pamięci.
_LEARNED_BAD = ("nie wiem", "nie potrafię", "nie moge", "nie mogę", "przepraszam",
                "nie rozumiem", "as an ai", "i cannot", "i'm sorry", "i am sorry",
                "error:", "traceback", "null", "undefined", "<|", "tool_call", "[tool")
_EN_STOP = (" the ", " and ", " is ", " are ", " of ", " with ", " this ", " that ")


# Źródła kuratorowane (ręcznie weryfikowane) — jedyne, które omijają bramkę jakości.
CURATED_SOURCES = ("facts", "first_aid")


def _qkey(text):
    """Znormalizowany klucz pytania (cache trafień): małe litery bez diakrytyków, BEZ interpunkcji.

    Wszystkie znaki niealfanumeryczne zamieniamy na spację (wcześniej tylko końce), więc
    „Co to jest fotosynteza?", „co, to jest fotosynteza" i „fotosynteza co to jest" się scalają."""
    q = normalize_facts(text or "")
    q = re.sub(r"[^a-z0-9 ]+", " ", q)
    return " ".join(q.split())


# Stopwords pytań (znormalizowane, bez diakrytyków) — nie liczą się do pokrycia leksykalnego.
_STOP_PL = frozenset((
    "co", "to", "jest", "sa", "jak", "jaka", "jakie", "jaki", "jakim", "dlaczego", "czym",
    "kto", "gdzie", "kiedy", "ile", "czy", "w", "we", "z", "ze", "do", "na", "o", "i", "a",
    "oraz", "lub", "ale", "nie", "tak", "ten", "ta", "to", "tego", "dla", "po", "od",
    "przez", "nad", "pod", "miedzy", "the", "of", "and", "sie", "sobie", "mozna",
))

# Sufiksy fleksyjne (kolejność od najdłuższych) do lekkiego rdzeniowania PL.
_STEM_SUFFIXES = ("ami", "ach", "owi", "ego", "emu", "ymi", "imi", "ow", "om",
                  "ie", "a", "e", "i", "o", "u", "y")


def _stem_pl(token):
    """Lekkie rdzeniowanie polskie: obcina typowe końcówki fleksyjne (na tekście bez diakrytyków)."""
    for suf in _STEM_SUFFIXES:
        if len(token) > len(suf) + 3 and token.endswith(suf):
            return token[:-len(suf)]
    return token


def _content_stems(text):
    """Zbiór rdzeni słów znaczących (bez stopwordów) dla leksykalnego pokrycia pytania."""
    norm = normalize_facts(text or "")
    out = set()
    for tok in re.findall(r"[a-z0-9]+", norm):
        if len(tok) >= 3 and tok not in _STOP_PL:
            out.add(_stem_pl(tok))
    return out


def _good_learned(title, text):
    """True, gdy wpis nadaje się do zapamiętania (długość, język, brak odmów/formatów)."""
    t = (text or "").strip()
    if len(t) < 20:
        return False
    low = " " + t.lower() + " "
    if any(b in low for b in _LEARNED_BAD):
        return False
    if t.lstrip().startswith(("{", "[")) or "```" in t:
        return False
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 12:
        return False
    english = sum(low.count(w) for w in _EN_STOP)
    if english >= 2:
        return False
    return True


class Memory:
    def __init__(self, db_path=":memory:", embedder=None):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.db_path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        # WAL + busy_timeout: usługa i batch (pre-teaching/destylacja) piszą równolegle do tej samej
        # bazy bez „database is locked"; zapis czeka zamiast paść. Bezpieczne dla lokalnego SQLite.
        try:
            self.con.execute("PRAGMA journal_mode=WAL")
            self.con.execute("PRAGMA busy_timeout=5000")
            self.con.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error:
            pass
        self.embedder = embedder
        # Cache wektorów celów trajektorii: LRU z limitem (C2) — wcześniej rósł bez ograniczeń.
        self._traj_cache = collections.OrderedDict()
        self._learned_index = None  # C2: cache macierzy wektorów `learned`
        self._profiles = None
        self._affect = None
        self._affect_memory = None
        self._humor = None
        self.con.executescript(SCHEMA)
        self._migrate()
        self._init_fts()
        self.con.commit()
        # Klucz biometrii: utwórz, jeśli brak; zaszyfruj stare (jawne) embeddingi twarzy/sylwetek.
        try:
            if biocrypto.available():
                self.encrypt_bio()
        except Exception:
            pass

    def _migrate(self):
        cols = {r["name"] for r in self.con.execute("PRAGMA table_info(learned)").fetchall()}
        if "url" not in cols:
            self.con.execute("ALTER TABLE learned ADD COLUMN url TEXT")
        if "qkey" not in cols:
            self.con.execute("ALTER TABLE learned ADD COLUMN qkey TEXT")
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_learned_qkey ON learned(qkey)")
        # Indeksy pod najczęstsze filtry/sortowania (backlog 2026-09-26).
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_learned_source ON learned(source)")
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_trajectories_kind ON trajectories(kind, ts)")
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_unknowns_hits ON unknowns(hits DESC)")
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_session_turns_ts ON session_turns(ts)")
        # Spójność wektorów: usunięcie wpisu `learned` kasuje też jego wektor (wcześniej zostawał
        # sierota i wracał w retrieval — C2). Plus jednorazowe sprzątanie istniejących sierot.
        try:
            self.con.execute(
                "CREATE TRIGGER IF NOT EXISTS learned_vectors_ad AFTER DELETE ON learned BEGIN "
                "DELETE FROM learned_vectors WHERE learned_id = old.id; END")
            self.con.execute(
                "DELETE FROM learned_vectors WHERE learned_id NOT IN (SELECT id FROM learned)")
        except sqlite3.Error:
            pass
        # Backfill kluczy. `user_version` wersjonuje SCHEMAT klucza: v0 -> v1 przelicza wszystkie
        # klucze po zmianie normalizacji (usunięcie interpunkcji wewnątrz).
        ver = self.con.execute("PRAGMA user_version").fetchone()[0]
        if ver < 1:
            for r in self.con.execute("SELECT id, title FROM learned").fetchall():
                self.con.execute("UPDATE learned SET qkey=? WHERE id=?",
                                 (_qkey(r["title"]), r["id"]))
            self.con.execute("PRAGMA user_version=1")
        else:
            missing = self.con.execute(
                "SELECT COUNT(*) c FROM learned WHERE qkey IS NULL OR qkey=''").fetchone()["c"]
            if missing:
                for r in self.con.execute("SELECT id, title FROM learned").fetchall():
                    self.con.execute("UPDATE learned SET qkey=? WHERE id=?",
                                     (_qkey(r["title"]), r["id"]))

    def _init_fts(self):
        self.fts = False
        self.fts_learned = False
        self.fts_traj = False
        try:
            self.con.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(text, tokenize='unicode61')")
            self.fts = True
        except sqlite3.OperationalError:
            self.fts = False
        # FTS wpisów `learned` (backlog 2026-09-26): szybkie kandydaty leksykalne przy ~7k wpisów
        # zamiast pełnego skanu `learned` w `find_learned_variant`. `remove_diacritics 2` scala
        # warianty z/bez diakrytyków (zapytanie normalizujemy bez diakrytyków).
        try:
            self.con.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS learned_fts USING fts5("
                "title, text, tokenize=\"unicode61 remove_diacritics 2\")")
            self.con.executescript("""
                CREATE TRIGGER IF NOT EXISTS learned_fts_ai AFTER INSERT ON learned BEGIN
                    INSERT INTO learned_fts(rowid, title, text)
                    VALUES (new.id, new.title, new.text);
                END;
                CREATE TRIGGER IF NOT EXISTS learned_fts_ad AFTER DELETE ON learned BEGIN
                    DELETE FROM learned_fts WHERE rowid = old.id;
                END;
                CREATE TRIGGER IF NOT EXISTS learned_fts_au AFTER UPDATE ON learned BEGIN
                    DELETE FROM learned_fts WHERE rowid = old.id;
                    INSERT INTO learned_fts(rowid, title, text)
                    VALUES (new.id, new.title, new.text);
                END;
            """)
            # Backfill jednorazowy (wpisy sprzed FTS).
            missing = self.con.execute(
                "SELECT COUNT(*) c FROM learned WHERE id NOT IN (SELECT rowid FROM learned_fts)"
            ).fetchone()["c"]
            if missing:
                self.con.execute(
                    "INSERT INTO learned_fts(rowid, title, text) "
                    "SELECT id, title, text FROM learned")
            self.fts_learned = True
        except sqlite3.OperationalError:
            self.fts_learned = False
        except sqlite3.Error:
            self.fts_learned = False
        # FTS trajektorii (backlog 2026-09-26): prefiltr kandydatów dla `similar_trajectories`
        # zamiast skanu wszystkich trajektorii przy każdym few-shot. Cele + odpowiedzi.
        try:
            self.con.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS trajectory_fts USING fts5("
                "goal, answer, tokenize=\"unicode61 remove_diacritics 2\")")
            self.con.executescript("""
                CREATE TRIGGER IF NOT EXISTS trajectory_fts_ai AFTER INSERT ON trajectories BEGIN
                    INSERT INTO trajectory_fts(rowid, goal, answer)
                    VALUES (new.id, new.goal, new.answer);
                END;
                CREATE TRIGGER IF NOT EXISTS trajectory_fts_ad AFTER DELETE ON trajectories BEGIN
                    DELETE FROM trajectory_fts WHERE rowid = old.id;
                END;
                CREATE TRIGGER IF NOT EXISTS trajectory_fts_au AFTER UPDATE ON trajectories BEGIN
                    DELETE FROM trajectory_fts WHERE rowid = old.id;
                    INSERT INTO trajectory_fts(rowid, goal, answer)
                    VALUES (new.id, new.goal, new.answer);
                END;
            """)
            missing = self.con.execute(
                "SELECT COUNT(*) c FROM trajectories "
                "WHERE id NOT IN (SELECT rowid FROM trajectory_fts)").fetchone()["c"]
            if missing:
                self.con.execute(
                    "INSERT INTO trajectory_fts(rowid, goal, answer) "
                    "SELECT id, goal, answer FROM trajectories")
            self.fts_traj = True
        except sqlite3.Error:
            self.fts_traj = False

    def _embed(self, text):
        if not self.embedder:
            return None
        try:
            vec = self.embedder(text)
            if vec is None:
                return None
            import numpy as np
            arr = np.asarray(vec, dtype="float32")
            norm = float(np.linalg.norm(arr))
            if norm > 0:
                arr = arr / norm
            return arr.tobytes()
        except Exception:
            return None

    def remember(self, text):
        text = (text or "").strip()
        if not text:
            return None
        cur = self.con.execute("INSERT INTO memories(ts, text, embedding) VALUES(?,?,?)",
                               (time.time(), text, self._embed(text)))
        if self.fts:
            self.con.execute("INSERT INTO memory_fts(rowid, text) VALUES(?,?)",
                             (cur.lastrowid, text))
        self.con.commit()
        return cur.lastrowid

    def all_memories(self):
        return [r["text"] for r in self.con.execute("SELECT text FROM memories ORDER BY id")]

    def search(self, query, k=5, min_score=0.35):
        query = (query or "").strip()
        if not query:
            return []
        if self.embedder:
            qv = self._embed(query)
            if qv is not None:
                hits = self._vector_search(qv, k, min_score)
                if hits:
                    return hits
        return self._fts_search(query, k)

    def _fts_search(self, query, k):
        tokens = [t for t in re.findall(r"\w+", query) if len(t) > 1]
        if not tokens:
            return []
        match = " OR ".join(tokens)
        try:
            rows = self.con.execute(
                "SELECT m.text FROM memory_fts f JOIN memories m ON m.id=f.rowid "
                "WHERE memory_fts MATCH ? ORDER BY rank LIMIT ?", (match, k)).fetchall()
            hits = [r["text"] for r in rows]
        except sqlite3.OperationalError:
            hits = []
        if not hits:
            hits = self._stem_search(tokens, k)
        return hits

    def _stem_search(self, tokens, k):
        """Zapas dla FTS: dopasowanie po rdzeniu (obcięta końcowa samogłoska) - polska odmiana."""
        stems = []
        for tok in tokens:
            stem = tok
            if len(stem) > 3 and stem[-1] in "aeiouy":
                stem = stem[:-1]
            stems.append(stem)
        where = " OR ".join(["text LIKE ?"] * len(stems))
        args = [f"%{s}%" for s in stems] + [k]
        rows = self.con.execute(
            f"SELECT text FROM memories WHERE {where} ORDER BY id DESC LIMIT ?", args).fetchall()
        return [r["text"] for r in rows]

    def _vector_search(self, qv, k, min_score):
        import numpy as np
        rows = self.con.execute(
            "SELECT text, embedding FROM memories WHERE embedding IS NOT NULL").fetchall()
        if not rows:
            return []
        q = np.frombuffer(qv, dtype="float32")
        scored = []
        for r in rows:
            v = np.frombuffer(r["embedding"], dtype="float32")
            if v.shape != q.shape:
                continue
            score = float(np.dot(q, v))
            if score >= min_score:
                scored.append((score, r["text"]))
        scored.sort(reverse=True)
        return [t for _, t in scored[:k]]

    @property
    def profiles(self):
        if self._profiles is None:
            from ..user.store import ProfileStore
            self._profiles = ProfileStore(self.con)
        return self._profiles

    @property
    def affect(self):
        if self._affect is None:
            from ..affect.store import AffectStore
            self._affect = AffectStore(self.con)
        return self._affect

    @property
    def affect_memory(self):
        if self._affect_memory is None:
            from ..affect.memory import AffectMemory
            self._affect_memory = AffectMemory(self.con)
        return self._affect_memory

    @property
    def humor(self):
        if self._humor is None:
            from ..persona.humor_store import HumorStore
            self._humor = HumorStore(self.con)
        return self._humor

    def profile(self):
        keys = ("imię", "imie", "nazywa", "mieszka", "adres", "lubi", "użytkownik",
                "uzytkownik", "jestem", "mam ")
        out = []
        for text in self.all_memories():
            low = text.lower()
            if any(k in low for k in keys):
                out.append(text)
        return out

    def add_episode(self, user, assistant, tools=None, ok=True):
        now = time.time()
        tool_names = ", ".join(tools or []) if isinstance(tools, (list, tuple)) else str(tools or "")
        self.con.execute("INSERT INTO conversations(ts, role, text) VALUES(?,?,?)",
                         (now, "user", user or ""))
        self.con.execute("INSERT INTO conversations(ts, role, text) VALUES(?,?,?)",
                         (now, "assistant", assistant or ""))
        self.add_trajectory(kind="episode", goal=user or "", result=tool_names,
                            answer=assistant or "", source="local", ok=bool(ok))
        self.con.commit()

    def conversations(self, limit=20):
        rows = self.con.execute(
            "SELECT role, text FROM conversations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"role": r["role"], "text": r["text"]} for r in reversed(rows)]

    def relationship_stats(self):
        """Statystyki relacji (P3): liczba tur, pierwsza i ostatnia interakcja.

        Liczone z `conversations` (append-only). Brak danych = same zera (nie rzuca)."""
        try:
            row = self.con.execute(
                "SELECT COUNT(*) c, MIN(ts) mn, MAX(ts) mx FROM conversations").fetchone()
        except sqlite3.Error:
            return {"turns": 0, "first_ts": 0.0, "last_ts": 0.0}
        return {"turns": int(row["c"] or 0), "first_ts": float(row["mn"] or 0.0),
                "last_ts": float(row["mx"] or 0.0)}

    def add_session_turn(self, user, assistant, ts=None):
        """Trwała pamięć robocza rozmowy (P2): para user/assistant dla bieżącej sesji."""
        self.con.execute("INSERT INTO session_turns(ts, user, assistant) VALUES(?,?,?)",
                         (time.time() if ts is None else ts, user or "", assistant or ""))
        self.con.commit()

    def recent_session_turns(self, limit=20):
        rows = self.con.execute(
            "SELECT ts, user, assistant FROM session_turns ORDER BY id DESC LIMIT ?",
            (max(1, int(limit)),)).fetchall()
        return [{"ts": float(r["ts"]), "user": r["user"], "assistant": r["assistant"]}
                for r in reversed(rows)]

    def session_summary(self):
        """(summary, last_ts) zwiniętego wątku sesji; ("", 0.0) gdy brak."""
        row = self.con.execute("SELECT summary, last_ts FROM session_meta WHERE id=1").fetchone()
        if not row:
            return "", 0.0
        return (row["summary"] or ""), float(row["last_ts"] or 0.0)

    def set_session_summary(self, summary, last_ts=None):
        self.con.execute(
            "INSERT INTO session_meta(id, summary, last_ts) VALUES(1,?,?) "
            "ON CONFLICT(id) DO UPDATE SET summary=excluded.summary, last_ts=excluded.last_ts",
            (summary or "", time.time() if last_ts is None else last_ts))
        self.con.commit()

    def session_turns_between(self, ts_start, ts_end):
        """Surowe tury z przedziału [ts_start, ts_end) — źródło dziennego digestu/archiwum."""
        rows = self.con.execute(
            "SELECT ts, user, assistant FROM session_turns WHERE ts >= ? AND ts < ? ORDER BY id",
            (float(ts_start), float(ts_end))).fetchall()
        return [{"ts": float(r["ts"]), "user": r["user"] or "", "assistant": r["assistant"] or ""}
                for r in rows]

    def context_digest(self, day):
        """Zapisany skrót dnia (P4); None gdy brak."""
        row = self.con.execute(
            "SELECT summary, turns, ts FROM context_digests WHERE day = ?", (str(day),)).fetchone()
        if not row:
            return None
        return {"summary": row["summary"] or "", "turns": int(row["turns"] or 0),
                "ts": float(row["ts"] or 0.0)}

    def context_digests(self, limit=14):
        rows = self.con.execute(
            "SELECT day, summary, turns, ts FROM context_digests ORDER BY day DESC LIMIT ?",
            (max(1, int(limit)),)).fetchall()
        return [{"day": r["day"], "summary": r["summary"] or "", "turns": int(r["turns"] or 0),
                 "ts": float(r["ts"] or 0.0)} for r in rows]

    def set_context_digest(self, day, summary, turns=0, ts=None):
        self.con.execute(
            "INSERT INTO context_digests(day, summary, turns, ts) VALUES(?,?,?,?) "
            "ON CONFLICT(day) DO UPDATE SET summary=excluded.summary, turns=excluded.turns, "
            "ts=excluded.ts",
            (str(day), summary or "", int(turns), time.time() if ts is None else ts))
        self.con.commit()

    def prune_session_turns(self, keep=200):
        self.con.execute(
            "DELETE FROM session_turns WHERE id NOT IN "
            "(SELECT id FROM session_turns ORDER BY id DESC LIMIT ?)", (max(1, int(keep)),))
        self.con.commit()

    def clear_session(self):
        self.con.execute("DELETE FROM session_turns")
        self.con.execute("DELETE FROM session_meta")
        self.con.commit()

    def add_lesson(self, text):
        text = (text or "").strip()
        if not text:
            return None
        row = self.con.execute("SELECT id, hits FROM lessons WHERE text=?", (text,)).fetchone()
        now = time.time()
        if row:
            self.con.execute("UPDATE lessons SET hits=hits+1, last=? WHERE id=?",
                             (now, row["id"]))
            self.con.commit()
            return row["id"]
        cur = self.con.execute(
            "INSERT INTO lessons(ts, text, last, hits, polarity) VALUES(?,?,?,?,?)",
            (now, text, now, 1, self._polarity(text)))
        self.con.commit()
        return cur.lastrowid

    @staticmethod
    def _polarity(text):
        neg = re.compile(r"\b(nie|nigdy|unikaj|bez|zakaz|wy[lł][aą]cz|nie wolno|odradzam)\b")
        return "negative" if neg.search(text.lower()) else "positive"

    def recent_lessons(self, n=5):
        rows = self.con.execute(
            "SELECT text FROM lessons ORDER BY last DESC LIMIT ?", (n,)).fetchall()
        return [r["text"] for r in rows]

    def search_lessons(self, query, n=5):
        rows = self.con.execute(
            "SELECT text FROM lessons WHERE text LIKE ? ORDER BY hits DESC LIMIT ?",
            (f"%{query}%", n)).fetchall()
        return [r["text"] for r in rows]

    def lesson_count(self):
        return self.con.execute("SELECT COUNT(*) c FROM lessons").fetchone()["c"]

    def prune_lessons(self, min_hits=0, max_age_days=180):
        cutoff = time.time() - max_age_days * 86400
        cur = self.con.execute(
            "DELETE FROM lessons WHERE hits<=? AND last<?", (min_hits, cutoff))
        self.con.commit()
        return cur.rowcount

    def review_lesson_drift(self):
        """Usuwa nowsze, sprzeczne lekcje (dryf): para 'X' i 'nie X' -> zostaje starsza."""
        rows = self.con.execute(
            "SELECT id, ts, text FROM lessons ORDER BY id").fetchall()
        norm = {}
        for r in rows:
            baseline = re.sub(r"\bnie\s+", "", normalize_facts(r["text"])).strip()
            norm.setdefault(baseline, []).append(r)
        removed = []
        for group in norm.values():
            neg = [r for r in group if self._polarity(r["text"]) == "negative"]
            pos = [r for r in group if self._polarity(r["text"]) == "positive"]
            while neg and pos:
                newer_neg = max(neg, key=lambda r: r["id"])
                newer_pos = max(pos, key=lambda r: r["id"])
                drop = newer_neg if newer_neg["id"] > newer_pos["id"] else newer_pos
                self.con.execute("DELETE FROM lessons WHERE id=?", (drop["id"],))
                removed.append(drop["id"])
                if drop is newer_neg:
                    neg.remove(newer_neg)
                else:
                    pos.remove(newer_pos)
        if removed:
            self.con.commit()
        return removed

    def _delete_memories(self, where, args=()):
        ids = [r["id"] for r in self.con.execute(
            f"SELECT id FROM memories WHERE {where}", args).fetchall()]
        if ids and self.fts:
            self.con.executemany("DELETE FROM memory_fts WHERE rowid=?", [(i,) for i in ids])
        if ids:
            self.con.executemany("DELETE FROM memories WHERE id=?", [(i,) for i in ids])

    def set_name(self, name):
        name = (name or "").strip()
        if not name:
            return False
        self._delete_memories("text LIKE ?", ("%imię%",))
        self.remember(f"użytkownik ma na imię {name}")
        return True

    def set_location(self, location):
        location = (location or "").strip()
        if not location:
            return False
        self._delete_memories("text LIKE ? OR text LIKE ?", ("%mieszka%", "%adres%"))
        self.remember(f"użytkownik mieszka: {location}")
        return True

    def learn_from_web(self, query, results_text):
        from ..tools.web import learn_from_web
        return learn_from_web(self, query, results_text)

    def add_trajectory(self, kind, goal, steps=None, result="", answer="", source="", ok=True):
        steps_json = json.dumps(steps, ensure_ascii=False) if steps is not None else None
        dup = self.con.execute(
            "SELECT id FROM trajectories WHERE kind=? AND goal=? AND COALESCE(answer,'')=?",
            (kind, goal, answer or "")).fetchone()
        if dup:
            return dup["id"]
        cur = self.con.execute(
            "INSERT INTO trajectories(ts, kind, goal, steps_json, result, answer, source, ok) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (time.time(), kind, goal, steps_json, result, answer, source, int(bool(ok))))
        traj_id = cur.lastrowid
        # Wektor celu liczony raz i zapisany: retrieval few-shot nie liczy embeddingów 700+ razy
        # na każde pytanie (wcześniej LRU thrashingował, gdy trajektorii było więcej niż limit cache).
        self._store_traj_vector(traj_id, goal)
        self.con.commit()
        return traj_id

    def trajectories(self, kind=None, limit=100):
        if kind:
            rows = self.con.execute(
                "SELECT * FROM trajectories WHERE kind=? ORDER BY id DESC LIMIT ?",
                (kind, limit)).fetchall()
        else:
            rows = self.con.execute(
                "SELECT * FROM trajectories ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def trajectory_count(self, kind=None):
        if kind:
            return self.con.execute("SELECT COUNT(*) c FROM trajectories WHERE kind=?",
                                    (kind,)).fetchone()["c"]
        return self.con.execute("SELECT COUNT(*) c FROM trajectories").fetchone()["c"]

    def _cache_lru(self, cache, key, value):
        """Wstaw do cache z limitem LRU (`ASTRO_TRAJ_CACHE_MAX`, domyślnie 512)."""
        cache[key] = value
        cache.move_to_end(key)
        try:
            cap = int(getattr(config, "TRAJ_CACHE_MAX", 512))
        except Exception:
            cap = 512
        if cap > 0:
            while len(cache) > cap:
                cache.popitem(last=False)

    def _traj_vec(self, text):
        """Wektor zapytania (cache LRU). None gdy brak embeddera/błąd.

        Uwaga: celowo dla ZAPYTANIA (krótka lista), nie dla wszystkich celów trajektorii —
        te mają wektory utrwalone w tabeli `trajectory_vectors` (patrz `_traj_vector`).
        """
        if text in self._traj_cache:
            self._traj_cache.move_to_end(text)
            return self._traj_cache[text]
        import numpy as np
        vec = None
        if self.embedder:
            try:
                raw = self._embed(text)
                if raw is not None:
                    vec = np.frombuffer(raw, dtype="float32")
            except Exception:
                vec = None
        self._cache_lru(self._traj_cache, text, vec)
        return vec

    def _store_traj_vector(self, traj_id, goal):
        """Liczy i utrwala wektor celu trajektorii (raz). Cicho pomija brak embeddera."""
        if not self.embedder or not goal:
            return
        raw = self._embed(goal)
        if raw is None:
            return
        self.con.execute(
            "INSERT OR REPLACE INTO trajectory_vectors(trajectory_id, embedding) VALUES(?,?)",
            (traj_id, raw))

    def _traj_vector(self, traj_id, goal):
        """Wektor celu trajektorii z DB; gdy brak — dolicza, zapisuje i zwraca."""
        import numpy as np
        if not self.embedder:
            return None
        row = self.con.execute(
            "SELECT embedding FROM trajectory_vectors WHERE trajectory_id=?",
            (traj_id,)).fetchone()
        if row is not None and row["embedding"]:
            return np.frombuffer(row["embedding"], dtype="float32")
        self._store_traj_vector(traj_id, goal)
        self.con.commit()
        row = self.con.execute(
            "SELECT embedding FROM trajectory_vectors WHERE trajectory_id=?",
            (traj_id,)).fetchone()
        if row is not None and row["embedding"]:
            return np.frombuffer(row["embedding"], dtype="float32")
        return None

    def backfill_trajectory_vectors(self, kind="agent"):
        """Dobudowuje wektory celów dla istniejących trajektorii (jednorazowo po migracji)."""
        if not self.embedder:
            return 0
        rows = self.con.execute(
            "SELECT t.id, t.goal FROM trajectories t "
            "LEFT JOIN trajectory_vectors v ON v.trajectory_id=t.id "
            "WHERE t.kind=? AND (v.embedding IS NULL) AND t.goal IS NOT NULL AND t.goal!=''",
            (kind,)).fetchall()
        n = 0
        for r in rows:
            self._store_traj_vector(r["id"], r["goal"])
            n += 1
        self.con.commit()
        return n

    def search_trajectory_ids_fts(self, query, kind="agent", limit=500):
        """Id trajektorii pasujących leksykalnie (FTS) — prefiltr dla `similar_trajectories`."""
        if not getattr(self, "fts_traj", False):
            return []
        toks = list(dict.fromkeys(t for t in self._tokens(query or "") if len(t) >= 3))
        if not toks:
            return []
        match = " OR ".join(toks)
        try:
            rows = self.con.execute(
                "SELECT f.rowid AS id FROM trajectory_fts f JOIN trajectories t ON t.id=f.rowid "
                "WHERE trajectory_fts MATCH ? AND t.kind=? AND t.ok=1 AND t.steps_json IS NOT NULL "
                "ORDER BY rank LIMIT ?", (match, kind, int(limit))).fetchall()
        except sqlite3.OperationalError:
            return []
        return [int(r["id"]) for r in rows]

    def similar_trajectories(self, query, k=1, min_score=None, kind="agent"):
        """Udane trajektorie narzędziowe podobne do zapytania (retrieval bez treningu wag).

        To realizuje „naukę w runtime": im więcej udanych epizodów, tym więcej wzorców
        `tool_call -> wynik` można podać modelowi jako few-shot. Z embedderem używa
        podobieństwa kosinusowego (lepsze dla parafraz), bez niego Jaccard po tokenach.
        """
        if not query:
            return []
        base = ("SELECT id, goal, steps_json, answer, result FROM trajectories "
                "WHERE kind=? AND ok=1 AND steps_json IS NOT NULL")
        rows = None
        if getattr(self, "fts_traj", False):
            ids = self.search_trajectory_ids_fts(query, kind=kind)
            if ids:
                marks = ",".join("?" * len(ids))
                rows = self.con.execute(base + f" AND id IN ({marks})",
                                        [kind] + ids).fetchall()
        if rows is None:
            rows = self.con.execute(base, (kind,)).fetchall()
        import numpy as np
        qv = self._traj_vec(query)
        embed_mode = qv is not None
        if min_score is None:
            default = getattr(config, "FEWSHOT_MIN_SCORE", 0.55)
            min_score = default if embed_mode else 0.34
        target = self._tokens(query)
        scored = []
        for r in rows:
            if embed_mode:
                tv = self._traj_vector(r["id"], r["goal"])
                if tv is not None and tv.shape == qv.shape:
                    score = float(np.dot(qv, tv))
                else:
                    score = self._jaccard(target, self._tokens(r["goal"]))
            else:
                score = self._jaccard(target, self._tokens(r["goal"]))
            if score >= min_score:
                scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, r in scored[:max(0, k)]:
            try:
                steps = json.loads(r["steps_json"] or "[]")
            except Exception:
                steps = []
            out.append({"goal": r["goal"], "steps": steps, "answer": r["answer"],
                        "score": round(score, 3)})
        return out

    def learning_stats(self):
        """Liczniki „nauki w runtime" (obserwowalność przyrostu wiedzy między sesjami)."""
        return {
            "agent_trajectories": self.trajectory_count("agent"),
            "episodes": self.trajectory_count("episode"),
            "learned": self.learned_count(),
            "lessons": self.lesson_count(),
            "unknowns": self.unknown_count(),
            "plans": self.plan_stats(),
        }

    def find_plan(self, goal, reuse=0.90):
        rows = self.con.execute(
            "SELECT goal, steps_json, ok, fail FROM plans WHERE steps_json IS NOT NULL"
        ).fetchall()
        best, best_score = None, 0.0
        target = self._tokens(goal)
        for r in rows:
            score = self._jaccard(target, self._tokens(r["goal"]))
            if score > best_score:
                best_score, best = score, r
        if best and best_score >= reuse:
            return {"goal": best["goal"], "steps": json.loads(best["steps_json"]),
                    "score": best_score}
        return None

    @staticmethod
    def _tokens(text):
        return set(re.findall(r"\w+", (text or "").lower()))

    @staticmethod
    def _jaccard(a, b):
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def record_plan_result(self, goal, steps, success):
        steps_json = json.dumps(steps, ensure_ascii=False)
        row = self.con.execute("SELECT id, ok, fail FROM plans WHERE goal=?", (goal,)).fetchone()
        now = time.time()
        if row:
            if success:
                self.con.execute("UPDATE plans SET ok=ok+1, fail=0, last=?, steps_json=? "
                                 "WHERE id=?", (now, steps_json, row["id"]))
            else:
                self.con.execute("UPDATE plans SET fail=fail+1, last=? WHERE id=?",
                                 (now, row["id"]))
        else:
            self.con.execute(
                "INSERT INTO plans(ts, last, goal, steps_json, ok, fail) VALUES(?,?,?,?,?,?)",
                (now, now, goal, steps_json, int(bool(success)), 0 if success else 1))
        self.con.commit()

    def plan_stats(self):
        row = self.con.execute(
            "SELECT COUNT(*) total, COALESCE(SUM(ok),0) ok, COALESCE(SUM(fail),0) fail "
            "FROM plans").fetchone()
        return {"total": row["total"], "ok": row["ok"], "fail": row["fail"]}

    def prune_plans(self, min_fail=3):
        cur = self.con.execute("DELETE FROM plans WHERE ok=0 AND fail>=?", (min_fail,))
        self.con.commit()
        return cur.rowcount

    def delete_plan(self, goal):
        cur = self.con.execute("DELETE FROM plans WHERE goal=?", (goal,))
        self.con.commit()
        return cur.rowcount

    def add_learned(self, topic, title, text, source="", verified=False, confidence=0.5,
                    url=""):
        title = (title or "").strip()
        text = (text or "").strip()
        if not text:
            return None
        # Bramka jakości: omijają ją WYŁĄCZNIE źródła kuratorowane ręcznie (facts/first_aid).
        # `verified=True` z sieci/legacy to tylko wyższa pewność — nie przepustka dla szumu
        # (angielski, odmowy, za krótkie), bo wcześniej wpuszczała śmieci do `learned`.
        if source not in CURATED_SOURCES and not _good_learned(title, text):
            return None
        # Dedup po znormalizowanym kluczu pytania (nie surowym tytule) — scala warianty zapisu.
        qk = _qkey(title)
        dup = None
        if qk:
            dup = self.con.execute(
                "SELECT id FROM learned WHERE qkey=? AND source=?", (qk, source)).fetchone()
        if dup is None:
            dup = self.con.execute(
                "SELECT id FROM learned WHERE title=? AND source=?", (title, source)).fetchone()
        if dup:
            return dup["id"]
        cur = self.con.execute(
            "INSERT INTO learned(ts, topic, title, text, source, verified, confidence, url, qkey) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (time.time(), topic, title, text, source, int(bool(verified)), float(confidence),
             url or "", _qkey(title)))
        row_id = cur.lastrowid
        if self.embedder and row_id:
            vec = self._embed(title or text)
            if vec:
                self.con.execute(
                    "INSERT OR REPLACE INTO learned_vectors(learned_id, embedding) VALUES(?,?)",
                    (row_id, vec))
        self.con.commit()
        return row_id

    # --- twarze: rozpoznawanie osób ---------------------------------------------------------
    def add_face(self, name, embedding, source="enroll"):
        """Dodaje/aktualizuje osobę (embedding twarzy SFace, 128-d). Zwraca id."""
        name = normalize_name(name)
        if not name or embedding is None:
            return None
        blob = _pack_emb(embedding)
        row = self.con.execute("SELECT id, count FROM faces WHERE name=?", (name,)).fetchone()
        now = time.time()
        if row:
            self.con.execute(
                "UPDATE faces SET embedding=?, count=count+1, last=?, source=? WHERE id=?",
                (blob, now, source, row["id"]))
            self.con.commit()
            return row["id"]
        cur = self.con.execute(
            "INSERT INTO faces(ts, name, embedding, count, last, source) VALUES(?,?,?,1,?,?)",
            (now, name, blob, now, source))
        self.con.commit()
        return cur.lastrowid

    def list_faces(self):
        rows = self.con.execute(
            "SELECT id, name, count, ts, last, source FROM faces ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def forget_face(self, name):
        cur = self.con.execute("DELETE FROM faces WHERE name=?", ((name or "").strip(),))
        self.con.commit()
        return cur.rowcount

    def match_face(self, embedding, threshold=0.40):
        """Najlepsze dopasowanie: (name|None, score). name tylko gdy score >= threshold."""
        best_name, best_score = None, 0.0
        for r in self.con.execute("SELECT name, embedding FROM faces").fetchall():
            s = _cosine(embedding, _unpack_emb(r["embedding"]))
            if s > best_score:
                best_name, best_score = r["name"], s
        if best_name and best_score >= float(threshold):
            return best_name, best_score
        return None, best_score

    # --- sylwetki (person re-ID) ------------------------------------------------------------
    def add_body(self, name, embedding, source="enroll"):
        """Dodaje/aktualizuje embedding sylwetki (YouTuReID, 768-d)."""
        name = normalize_name(name)
        if not name or embedding is None:
            return None
        blob = _pack_emb(embedding)
        row = self.con.execute("SELECT id FROM bodies WHERE name=?", (name,)).fetchone()
        now = time.time()
        if row:
            self.con.execute(
                "UPDATE bodies SET embedding=?, count=count+1, last=?, source=? WHERE id=?",
                (blob, now, source, row["id"]))
            self.con.commit()
            return row["id"]
        cur = self.con.execute(
            "INSERT INTO bodies(ts, name, embedding, count, last, source) VALUES(?,?,?,1,?,?)",
            (now, name, blob, now, source))
        self.con.commit()
        return cur.lastrowid

    def list_bodies(self):
        rows = self.con.execute("SELECT id, name, count, ts, last FROM bodies ORDER BY name") \
            .fetchall()
        return [dict(r) for r in rows]

    def match_body(self, embedding, threshold=0.55):
        """Najlepsze dopasowanie sylwetki: (name|None, score)."""
        best_name, best_score = None, 0.0
        for r in self.con.execute("SELECT name, embedding FROM bodies").fetchall():
            s = _cosine(embedding, _unpack_emb(r["embedding"]))
            if s > best_score:
                best_name, best_score = r["name"], s
        if best_name and best_score >= float(threshold):
            return best_name, best_score
        return None, best_score

    def forget_person(self, name):
        """Usuwa osobę z obu baz (twarz + sylwetka). Zwraca łączną liczbę usunięć."""
        name = normalize_name(name)
        n = self.con.execute("DELETE FROM faces WHERE name=?", (name,)).rowcount
        n += self.con.execute("DELETE FROM bodies WHERE name=?", (name,)).rowcount
        self.con.commit()
        return n

    def add_sighting(self, name, score=0.0, known=True):
        self.con.execute(
            "INSERT INTO face_sightings(ts, name, score, known) VALUES(?,?,?,?)",
            (time.time(), name or "?", float(score), int(bool(known))))
        self.con.commit()

    def add_vision_note(self, kind, text, ts=None):
        """Zapisuje notatkę z wizji (np. odczyt OCR) — spięcie z pamięcią długoterminową."""
        self.con.execute("INSERT INTO vision_notes(ts, kind, text) VALUES(?,?,?)",
                         (time.time() if ts is None else float(ts), str(kind or ""),
                          str(text or "")))
        self.con.commit()

    def recent_vision_notes(self, limit=10, kinds=None):
        """Ostatnie notatki wizji (kolejność malejąca). `kinds` = filtr (np. ("ocr",))."""
        sql = ("SELECT ts, kind, text FROM vision_notes "
               + ("WHERE kind IN (%s) " % ",".join("?" * len(kinds)) if kinds else "")
               + "ORDER BY id DESC LIMIT ?")
        args = list(kinds or []) + [int(limit)]
        rows = self.con.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def encrypt_bio(self):
        """Szyfruje istniejące embeddingi twarzy/sylwetek (migracja jawnych -> AES-GCM).

        Zwraca liczbę zmienionych wpisów. Bezpieczne do wielokrotnego wywołania.
        """
        changed = 0
        for table in ("faces", "bodies"):
            for r in self.con.execute(f"SELECT id, embedding FROM {table}").fetchall():
                blob = r["embedding"]
                if not blob or biocrypto.is_encrypted(blob):
                    continue
                self.con.execute(f"UPDATE {table} SET embedding=? WHERE id=?",
                                 (biocrypto.encrypt(blob), r["id"]))
                changed += 1
        if changed:
            self.con.commit()
        return changed

    def purge_sightings(self, days=None):
        """Usuwa zobaczenia starsze niż `days` (domyślnie `SIGHTINGS_RETENTION_DAYS`)."""
        days = int(getattr(config, "SIGHTINGS_RETENTION_DAYS", 90) if days is None else days)
        if days <= 0:
            return 0
        cutoff = time.time() - days * 86400
        n = self.con.execute("DELETE FROM face_sightings WHERE ts < ?", (cutoff,)).rowcount
        self.con.commit()
        return n

    def recent_sightings(self, limit=10):
        rows = self.con.execute(
            "SELECT ts, name, score, known FROM face_sightings ORDER BY id DESC LIMIT ?",
            (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    def sightings_since(self, since, names_only=False):
        """Zobaczenia (rozpoznane osoby) od czasu `since` (epoch). Domyślnie tylko znane imiona."""
        sql = ("SELECT ts, name, score, known FROM face_sightings WHERE ts >= ? AND name<>'?'"
               " ORDER BY ts")
        rows = self.con.execute(sql, (float(since),)).fetchall()
        return [dict(r) for r in rows]

    def sightings_summary(self, day_start=None, limit=10):
        """Podsumowanie: kto był i ile razy (od `day_start`, domyślnie od początku dnia).

        Zwraca listę {name, count, first, last} posortowaną po ostatnim zobaczeniu (malejąco).
        """
        import time as _t
        if day_start is None:
            lt = _t.localtime()
            day_start = _t.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        rows = self.con.execute(
            "SELECT name, COUNT(*) c, MIN(ts) first, MAX(ts) last FROM face_sightings "
            "WHERE ts >= ? AND name<>'?' GROUP BY name ORDER BY last DESC LIMIT ?",
            (float(day_start), int(limit))).fetchall()
        return [{"name": r["name"], "count": r["c"], "first": r["first"],
                 "last": r["last"]} for r in rows]

    def backfill_learned_vectors(self, sources=None, limit=0):
        """Dobudowuje wektory dla istniejących wpisów `learned` (embedding po tytule)."""
        if not self.embedder:
            return 0
        where = ""
        args = []
        if sources:
            marks = ",".join("?" * len(sources))
            where = f"WHERE source IN ({marks})"
            args = list(sources)
        sql = ("SELECT l.id, l.title, l.text FROM learned l "
               "LEFT JOIN learned_vectors v ON v.learned_id=l.id "
               "WHERE v.learned_id IS NULL" + (f" AND {where[6:]}" if where else ""))
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self.con.execute(sql, args).fetchall()
        done = 0
        for r in rows:
            vec = self._embed(r["title"] or r["text"])
            if not vec:
                continue
            self.con.execute(
                "INSERT OR REPLACE INTO learned_vectors(learned_id, embedding) VALUES(?,?)",
                (r["id"], vec))
            done += 1
        self.con.commit()
        return done

    def learned_vector_count(self):
        return self.con.execute("SELECT COUNT(*) c FROM learned_vectors").fetchone()["c"]

    def _learned_matrix(self, q):
        """Zindeksowana macierz wektorów `learned` (N x d) + tytuły/teksty.

        C2: macierz budowana raz i trzymana w pamięci, dopóki nie zmieni się zbiór wektorów
        (sygnatura = liczba + max id w `learned_vectors`). Wcześniej skan+`vstack` leciał przy
        KAŻDYM pytaniu; teraz powtórne zapytania nie dotykają bazy poza tanim COUNT/MAX.
        """
        import numpy as np
        dim = int(q.shape[0])
        sig = self._learned_vector_sig()
        idx = self._learned_index
        if (idx is not None and idx["sig"] == sig and idx["dim"] == dim):
            return idx["matrix"], idx["titles"], idx["texts"]
        rows = self.con.execute(
            "SELECT l.title, l.text, v.embedding FROM learned l "
            "JOIN learned_vectors v ON v.learned_id=l.id WHERE v.embedding IS NOT NULL").fetchall()
        titles, texts, vecs = [], [], []
        for r in rows:
            v = np.frombuffer(r["embedding"], dtype="float32")
            if v.shape != q.shape:
                continue
            titles.append(r["title"] or "")
            texts.append(r["text"] or "")
            vecs.append(v)
        if not vecs:
            self._learned_index = None
            return None
        matrix = np.vstack(vecs)
        self._learned_index = {"sig": sig, "dim": dim, "matrix": matrix,
                               "titles": titles, "texts": texts}
        return matrix, titles, texts

    def _learned_vector_sig(self):
        """Sygnatura zbioru wektorów (invalidacja cache macierzy)."""
        try:
            row = self.con.execute(
                "SELECT COUNT(*) c, COALESCE(MAX(learned_id), 0) m FROM learned_vectors"
            ).fetchone()
            return (int(row["c"]), int(row["m"]))
        except sqlite3.Error:
            return (0, 0)

    def learned_index_info(self):
        """Diagnostyka indeksu (C2): rozmiar macierzy w pamięci i jego sygnatura."""
        idx = self._learned_index
        if not idx:
            return {"cached": False}
        return {"cached": True, "rows": int(idx["matrix"].shape[0]),
                "dim": int(idx["matrix"].shape[1]), "sig": idx["sig"]}

    def search_learned_semantic(self, query, k=3, min_score=0.80):
        """Retrieval embeddingowy wpisów `learned` (cosine po pytaniu). Precyzyjniejszy niż
        przecięcie tokenów - nie myli pytań dzielących słowa funkcyjne („co to jest ...")."""
        if not self.embedder:
            return []
        qv = self._embed(query)
        if qv is None:
            return []
        import numpy as np
        q = np.frombuffer(qv, dtype="float32")
        mat = self._learned_matrix(q)
        if mat is None:
            return []
        matrix, _titles, texts = mat
        scores = matrix @ q
        idx = np.where(scores >= min_score)[0]
        if idx.size == 0:
            return []
        order = idx[np.argsort(-scores[idx])][:k]
        return [texts[int(i)] for i in order]

    def _learned_hybrid_match(self, query):
        """Trafienie w `learned` łączące semantykę z pokryciem leksykalnym (rdzenie pytania).

        Sam embedding zwraca wysokie podobieństwo dla pytań pokrewnych tematycznie, ale innych
        znaczeniowo („odmówić zaproszenia" vs „elementy zaproszenia", „commit" vs „O(n)").
        Dlatego kandydatów rankingujemy po `sem + W * lex`, a przyjmujemy tylko gdy są bardzo
        blisko semantycznie LUB mają wsparcie słów pytania. Zwraca tekst albo None.

        Wydajność: semantyka liczona macierzowo; leksykę liczymy tylko dla realnych kandydatów
        (`sem >= best_sem - W`, bo leksyka dodaje co najwyżej W) — wynik identyczny jak pełny skan.
        """
        if not self.embedder:
            return None
        qv = self._embed(query)
        if qv is None:
            return None
        import numpy as np
        q = np.frombuffer(qv, dtype="float32")
        mat = self._learned_matrix(q)
        if mat is None:
            return None
        matrix, titles, texts = mat
        floor = float(getattr(config, "LEARNED_FLOOR", 0.60))
        sem_strong = float(getattr(config, "LEARNED_SEM_STRONG", 0.86))
        sem_mid = float(getattr(config, "LEARNED_SEM_MID", 0.72))
        lex_mid = float(getattr(config, "LEARNED_LEX_MID", 0.5))
        sem_weak = float(getattr(config, "LEARNED_SEM_WEAK", 0.78))
        lex_weak = float(getattr(config, "LEARNED_LEX_WEAK", 0.25))
        lex_w = float(getattr(config, "LEARNED_LEX_W", 0.16))
        sems = matrix @ q
        best_sem = float(sems.max())
        if best_sem < floor:
            return None
        ql = _content_stems(query)
        thr = max(floor, best_sem - lex_w)
        best = None  # (hybrid, sem, lex, text)
        for i in np.where(sems >= thr)[0]:
            sem = float(sems[i])
            lex = 0.0
            if ql:
                tl = _content_stems(titles[int(i)])
                if tl:
                    lex = len(ql & tl) / len(ql)
            hybrid = sem + lex_w * lex
            if best is None or hybrid > best[0]:
                best = (hybrid, sem, lex, texts[int(i)])
        if best is None:
            return None
        _hybrid, sem, lex, text = best
        if (sem >= sem_strong
                or (sem >= sem_mid and lex >= lex_mid)
                or (sem >= sem_weak and lex >= lex_weak)):
            return text
        return None

    def search_learned(self, query, k=3):
        rows = self.con.execute(
            "SELECT title, text FROM learned WHERE text LIKE ? OR title LIKE ? "
            "ORDER BY confidence DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", k)).fetchall()
        return [r["text"] for r in rows]

    def find_learned_exact(self, query):
        """Dokładny wpis `learned` po znormalizowanym kluczu pytania (cache re-asków)."""
        qk = _qkey(query)
        if not qk:
            return None
        row = self.con.execute(
            "SELECT text FROM learned WHERE qkey=? ORDER BY confidence DESC, ts DESC LIMIT 1",
            (qk,)).fetchone()
        text = (row["text"] if row else "") or ""
        return text.strip() or None

    def _qkey_tokens(self, qk):
        return {t for t in (qk or "").split() if len(t) >= 3}

    def find_learned_variant(self, query, min_overlap=0.9, max_scan=20000):
        """Wariant pytania: wysokie przecięcie tokenów znormalizowanych kluczy (przestawienia,
        drobne różnice). Próg wysoki (0.9), by nie mylić pytań dzielących słowa funkcyjne."""
        q = self._qkey_tokens(_qkey(query))
        if not q or (len(q) < 2 and not any(len(t) >= 6 for t in q)):
            return None
        best, best_score = None, 0.0
        rows = self.con.execute(
            "SELECT qkey, text FROM learned WHERE qkey IS NOT NULL AND qkey<>'' "
            "ORDER BY confidence DESC LIMIT ?", (max_scan,)).fetchall()
        for r in rows:
            toks = self._qkey_tokens(r["qkey"])
            if not toks:
                continue
            score = len(q & toks) / len(q)
            if score > best_score:
                best, best_score = r["text"], score
        return best.strip() if best and best_score >= min_overlap else None

    def _learned_fts_tokens(self, query):
        toks = [t for t in re.findall(r"[a-z0-9]+", normalize_facts(query or ""))
                if len(t) >= 3 and t not in _STOP_PL]
        return list(dict.fromkeys(toks))

    def search_learned_fts(self, query, k=8):
        """Kandydaci leksykalni z `learned_fts` (bez skanu całej tabeli). [(title, text)]."""
        if not getattr(self, "fts_learned", False):
            return []
        toks = self._learned_fts_tokens(query)
        if not toks:
            return []
        match = " OR ".join(toks)
        try:
            rows = self.con.execute(
                "SELECT l.title, l.text FROM learned_fts f JOIN learned l ON l.id = f.rowid "
                "WHERE learned_fts MATCH ? ORDER BY rank LIMIT ?", (match, int(k))).fetchall()
        except sqlite3.OperationalError:
            return []
        return [(r["title"] or "", r["text"] or "") for r in rows]

    def find_learned_fts(self, query, min_overlap=0.6, k=8):
        """Najlepszy leksykalny wpis `learned` z kandydatów FTS (ranking po pokryciu rdzeni)."""
        q = _content_stems(query)
        if not q:
            return None
        best, best_score = None, 0.0
        for title, text in self.search_learned_fts(query, k=k):
            tl = _content_stems(title)
            score = len(q & tl) / len(q) if tl else 0.0
            if score > best_score:
                best, best_score = text, score
        return best.strip() if best and best_score >= min_overlap else None

    def best_learned(self, query, min_overlap=0.6, max_scan=20000):
        """Najlepszy wpis `learned` dla pytania.

        Kolejność: (1) dokładny znormalizowany klucz (re-ask/wariant pisowni — natychmiast),
        (2) retrieval embeddingowy (parafrazy), (3) wariant po tokenach klucza (gdy brak
        embeddera albo wektory nie trafiły), (4) FTS `learned_fts` (szybkie kandydaty leksykalne)."""
        exact = self.find_learned_exact(query)
        if exact:
            return exact
        if self.embedder:
            try:
                semantic = self._learned_hybrid_match(query)
            except Exception:
                semantic = None
            if semantic:
                return semantic
        variant = self.find_learned_variant(query)
        if variant:
            return variant
        if self.embedder:
            return None
        if getattr(self, "fts_learned", False):
            fts_hit = self.find_learned_fts(query, min_overlap=min_overlap)
            if fts_hit:
                return fts_hit
        q = {t for t in self._tokens(query or "") if len(t) >= 3}
        if not q or (len(q) < 2 and not any(len(t) >= 6 for t in q)):
            return None
        best, best_score = None, 0.0
        rows = self.con.execute(
            "SELECT title, text FROM learned ORDER BY confidence DESC LIMIT ?",
            (max_scan,)).fetchall()
        for r in rows:
            toks = self._tokens((r["title"] or "") + " " + (r["text"] or ""))
            if not toks:
                continue
            score = len(q & toks) / len(q)
            if score > best_score:
                best, best_score = r["text"], score
        if best and best_score >= min_overlap:
            return best.strip()
        return None

    def learned_count(self):
        return self.con.execute("SELECT COUNT(*) c FROM learned").fetchone()["c"]

    def learned_verified_count(self):
        return self.con.execute("SELECT COUNT(*) c FROM learned WHERE verified=1").fetchone()["c"]

    def learned_titles(self):
        return {r["title"] for r in self.con.execute("SELECT title FROM learned").fetchall()}

    def record_unknown(self, text):
        text = (text or "").strip()
        if not text or len(text) > 200:
            return None
        row = self.con.execute("SELECT id, hits FROM unknowns WHERE text=?", (text,)).fetchone()
        if row:
            self.con.execute("UPDATE unknowns SET hits=hits+1 WHERE id=?", (row["id"],))
            self.con.commit()
            return row["id"]
        cur = self.con.execute("INSERT INTO unknowns(ts, text, hits) VALUES(?,?,1)",
                               (time.time(), text))
        self.con.commit()
        return cur.lastrowid

    def top_unknowns(self, n=10):
        rows = self.con.execute(
            "SELECT text, hits FROM unknowns ORDER BY hits DESC LIMIT ?", (n,)).fetchall()
        return [(r["text"], r["hits"]) for r in rows]

    def delete_unknown(self, text):
        """Usuwa pytanie z `unknowns` (po nauczeniu odpowiedzi) — zamyka pętlę samodoskonalenia."""
        cur = self.con.execute("DELETE FROM unknowns WHERE text=?", ((text or "").strip(),))
        self.con.commit()
        return cur.rowcount

    def unknown_count(self):
        return self.con.execute("SELECT COUNT(*) c FROM unknowns").fetchone()["c"]

    def close(self):
        try:
            self.con.close()
        except Exception:
            pass


def default_memory(embedder=None):
    from .. import config
    if embedder is None and config.EMBED_MODEL:
        try:
            from .embed import OllamaEmbedder
            embedder = OllamaEmbedder(config.LLM_URL, config.EMBED_MODEL)
        except Exception:
            embedder = None
    config.ensure_dirs()
    return Memory(config.DB_PATH, embedder=embedder)
