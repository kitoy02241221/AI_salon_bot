import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .domain import Salon


class SQLiteStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "salons").mkdir(exist_ok=True)
        self.catalog_path = root / "catalog.sqlite3"
        with self._connect(self.catalog_path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS salons (
                    id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL, city TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS sessions (
                    user_id INTEGER NOT NULL, chat_id INTEGER NOT NULL,
                    salon_id TEXT, searching INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(user_id, chat_id));
                CREATE INDEX IF NOT EXISTS idx_salon_name ON salons(name);
                CREATE TABLE IF NOT EXISTS search_terms (
                    salon_id TEXT NOT NULL, term TEXT NOT NULL,
                    PRIMARY KEY(salon_id, term));
                CREATE INDEX IF NOT EXISTS idx_search_term ON search_terms(term);
            """)

    @staticmethod
    @contextmanager
    def _connect(path: Path):
        db = sqlite3.connect(path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _salon(row) -> Salon | None:
        return Salon(row["id"], row["code"], row["name"], row["city"]) if row else None

    def add_salon(self, name: str, city: str, facts: list[str]) -> Salon:
        if not name.strip() or not city.strip() or not facts or any(not f.strip() for f in facts):
            raise ValueError("Нужны название, город и непустые факты")
        salon = Salon(uuid.uuid4().hex, "s_" + secrets.token_urlsafe(12), name.strip(), city.strip())
        path = self.root / "salons" / (salon.id + ".sqlite3")
        with self._connect(path) as db:
            db.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, content TEXT NOT NULL)")
            db.execute("CREATE VIRTUAL TABLE facts_fts USING fts5(content, content='facts', content_rowid='id')")
            db.executemany("INSERT INTO facts(content) VALUES (?)", [(f.strip(),) for f in facts])
            db.execute("INSERT INTO facts_fts(facts_fts) VALUES('rebuild')")
        try:
            with self._connect(self.catalog_path) as db:
                db.execute("INSERT INTO salons(id,code,name,city) VALUES (?,?,?,?)",
                           (salon.id, salon.code, salon.name, salon.city))
                terms = {salon.name.casefold(), salon.city.casefold()}
                terms.update(re.findall(r"[\w]+", (salon.name + " " + salon.city).casefold()))
                db.executemany("INSERT INTO search_terms(salon_id,term) VALUES (?,?)",
                               [(salon.id, term) for term in terms])
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return salon

    def by_code(self, code: str) -> Salon | None:
        with self._connect(self.catalog_path) as db:
            return self._salon(db.execute("SELECT * FROM salons WHERE code=? AND active=1", (code,)).fetchone())

    def by_id(self, salon_id: str) -> Salon | None:
        with self._connect(self.catalog_path) as db:
            return self._salon(db.execute("SELECT * FROM salons WHERE id=? AND active=1", (salon_id,)).fetchone())

    def list_active(self) -> list[Salon]:
        with self._connect(self.catalog_path) as db:
            return [self._salon(row) for row in db.execute(
                "SELECT * FROM salons WHERE active=1 ORDER BY name")]

    def search(self, query: str, limit: int = 8) -> list[Salon]:
        # Bound work and return a short list; index/search service can replace this adapter.
        q = query.strip()[:80]
        if len(q) < 2:
            return []
        needle = q.casefold()
        with self._connect(self.catalog_path) as db:
            rows = db.execute("""SELECT DISTINCT salons.* FROM salons
                JOIN search_terms ON search_terms.salon_id=salons.id
                WHERE salons.active=1 AND search_terms.term>=? AND search_terms.term<?
                ORDER BY salons.name LIMIT ?""", (needle, needle + "\uffff", limit)).fetchall()
        return [self._salon(r) for r in rows]

    def get(self, user_id: int, chat_id: int) -> tuple[str | None, bool]:
        with self._connect(self.catalog_path) as db:
            row = db.execute("SELECT salon_id, searching FROM sessions WHERE user_id=? AND chat_id=?",
                             (user_id, chat_id)).fetchone()
        return (row["salon_id"], bool(row["searching"])) if row else (None, False)

    def set(self, user_id: int, chat_id: int, salon_id: str | None, searching: bool) -> None:
        with self._connect(self.catalog_path) as db:
            db.execute("""INSERT INTO sessions(user_id,chat_id,salon_id,searching) VALUES (?,?,?,?)
                ON CONFLICT(user_id,chat_id) DO UPDATE SET salon_id=excluded.salon_id,
                    searching=excluded.searching""", (user_id, chat_id, salon_id, int(searching)))

    def relevant(self, salon_id: str, question: str, limit: int = 16) -> list[str]:
        if not self.by_id(salon_id) or not re.fullmatch(r"[0-9a-f]{32}", salon_id):
            return []
        path = self.root / "salons" / (salon_id + ".sqlite3")
        # File creation is forbidden on read; never use an untrusted path as a database name.
        if not path.is_file() or path.is_symlink():
            return []
        tokens = re.findall(r"\w{3,}", question.casefold())[:12]
        with self._connect(path) as db:
            count = db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            if count <= limit:
                return [row["content"] for row in db.execute("SELECT content FROM facts ORDER BY id")]
            if tokens:
                query = " OR ".join('"' + token + '"' for token in tokens)
                rows = db.execute("""SELECT facts.content FROM facts_fts
                    JOIN facts ON facts.id=facts_fts.rowid
                    WHERE facts_fts MATCH ? ORDER BY bm25(facts_fts) LIMIT ?""",
                    (query, limit)).fetchall()
                if rows:
                    return [row["content"] for row in rows]
            # General questions may still need a short overview of this salon.
            rows = db.execute("SELECT content FROM facts ORDER BY id LIMIT ?", (min(limit, 6),)).fetchall()
            return [row["content"] for row in rows]
