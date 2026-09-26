import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .domain import DISTRICTS, Salon, ServiceItem, SessionState


class SQLiteStore:
    CITY = "Калининград"

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "salons").mkdir(exist_ok=True)
        self.catalog_path = root / "catalog.sqlite3"
        with self._connect(self.catalog_path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS salons (
                    id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL, city TEXT NOT NULL,
                    district TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS sessions (
                    user_id INTEGER NOT NULL, chat_id INTEGER NOT NULL,
                    salon_id TEXT, district TEXT, mode TEXT NOT NULL DEFAULT 'districts',
                    PRIMARY KEY(user_id, chat_id));
                CREATE INDEX IF NOT EXISTS idx_salon_name ON salons(name);
                CREATE TABLE IF NOT EXISTS search_terms (
                    salon_id TEXT NOT NULL, term TEXT NOT NULL,
                    PRIMARY KEY(salon_id, term));
                CREATE INDEX IF NOT EXISTS idx_search_term ON search_terms(term);
            """)
            self._add_column(db, "salons", "district", "TEXT NOT NULL DEFAULT ''")
            self._add_column(db, "salons", "address", "TEXT NOT NULL DEFAULT ''")
            self._add_column(db, "sessions", "district", "TEXT")
            self._add_column(db, "sessions", "mode", "TEXT NOT NULL DEFAULT 'districts'")
            db.execute("CREATE INDEX IF NOT EXISTS idx_salon_district ON salons(district)")
            self._rebuild_search_terms(db)

    @staticmethod
    def _add_column(db: sqlite3.Connection, table: str, name: str, definition: str) -> None:
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @staticmethod
    def _rebuild_search_terms(db: sqlite3.Connection) -> None:
        """Keep search strictly name-based, including after legacy migrations."""
        db.execute("DELETE FROM search_terms")
        rows = db.execute("SELECT id,name FROM salons").fetchall()
        terms: list[tuple[str, str]] = []
        for row in rows:
            values = {row["name"].casefold()}
            values.update(re.findall(r"[\w]+", row["name"].casefold()))
            terms.extend((row["id"], value) for value in values)
        db.executemany("INSERT INTO search_terms(salon_id,term) VALUES (?,?)", terms)

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
        if not row:
            return None
        return Salon(
            row["id"], row["code"], row["name"], row["city"],
            row["district"], row["address"],
        )

    @staticmethod
    def _extract_services(facts: list[str]) -> list[ServiceItem]:
        services: list[ServiceItem] = []
        seen: set[str] = set()
        patterns = (
            re.compile(
                r"^\s*([^:\n]{2,100}?)\s+[—-]\s*((?:от\s+)?\d[\d\s]*\s*(?:₽|руб(?:лей|ля|ль)?))",
                re.IGNORECASE,
            ),
            re.compile(
                r"^\s*([^:\n]{2,100}?)\s+стоит\s+((?:от\s+)?\d[\d\s]*\s*(?:₽|руб(?:лей|ля|ль)?))",
                re.IGNORECASE,
            ),
        )
        for fact in facts:
            for line in fact.splitlines():
                match = None
                for pattern in patterns:
                    match = pattern.search(line)
                    if match:
                        break
                if not match:
                    continue
                name = match.group(1).strip(" .—-")
                price = match.group(2).strip(" .")
                key = name.casefold()
                if key not in seen:
                    services.append(ServiceItem(name, price))
                    seen.add(key)
        return services

    def _tenant_path(self, salon_id: str) -> Path | None:
        if not re.fullmatch(r"[0-9a-f]{32}", salon_id):
            return None
        path = self.root / "salons" / (salon_id + ".sqlite3")
        return path if path.is_file() and not path.is_symlink() else None

    def _ensure_tenant_schema(self, path: Path) -> None:
        with self._connect(path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                price TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0)""")
            if db.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 0:
                facts = [row["content"] for row in db.execute("SELECT content FROM facts ORDER BY id")]
                services = self._extract_services(facts)
                db.executemany(
                    "INSERT INTO services(name,price,sort_order) VALUES (?,?,?)",
                    [(item.name, item.price, index) for index, item in enumerate(services)],
                )

    def add_salon(self, name: str, district: str, address: str, facts: list[str]) -> Salon:
        if district not in DISTRICTS.values():
            raise ValueError("Район должен быть Центральный, Ленинградский или Московский")
        if not name.strip() or not address.strip() or not facts or any(not f.strip() for f in facts):
            raise ValueError("Нужны название, район, точный адрес и непустые факты")
        salon = Salon(
            uuid.uuid4().hex,
            "s_" + secrets.token_urlsafe(12),
            name.strip(),
            self.CITY,
            district,
            address.strip(),
        )
        path = self.root / "salons" / (salon.id + ".sqlite3")
        with self._connect(path) as db:
            db.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, content TEXT NOT NULL)")
            db.execute("CREATE VIRTUAL TABLE facts_fts USING fts5(content, content='facts', content_rowid='id')")
            db.executemany("INSERT INTO facts(content) VALUES (?)", [(f.strip(),) for f in facts])
            db.execute("INSERT INTO facts_fts(facts_fts) VALUES('rebuild')")
        self._ensure_tenant_schema(path)
        try:
            with self._connect(self.catalog_path) as db:
                db.execute(
                    "INSERT INTO salons(id,code,name,city,district,address) VALUES (?,?,?,?,?,?)",
                    (salon.id, salon.code, salon.name, salon.city, salon.district, salon.address),
                )
                terms = {salon.name.casefold()}
                terms.update(re.findall(r"[\w]+", salon.name.casefold()))
                db.executemany(
                    "INSERT INTO search_terms(salon_id,term) VALUES (?,?)",
                    [(salon.id, term) for term in terms],
                )
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return salon

    def update_location(self, salon_id: str, district: str, address: str) -> Salon:
        if district not in DISTRICTS.values() or not address.strip():
            raise ValueError("Укажите допустимый район и точный адрес")
        with self._connect(self.catalog_path) as db:
            cursor = db.execute(
                "UPDATE salons SET city=?,district=?,address=? WHERE id=?",
                (self.CITY, district, address.strip(), salon_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Салон с таким ID не найден")
        return self.by_id(salon_id)

    def by_code(self, code: str) -> Salon | None:
        with self._connect(self.catalog_path) as db:
            row = db.execute(
                "SELECT * FROM salons WHERE code=? AND active=1 AND city=?",
                (code, self.CITY),
            ).fetchone()
        return self._salon(row)

    def by_id(self, salon_id: str) -> Salon | None:
        with self._connect(self.catalog_path) as db:
            row = db.execute(
                "SELECT * FROM salons WHERE id=? AND active=1 AND city=?",
                (salon_id, self.CITY),
            ).fetchone()
        return self._salon(row)

    def list_active(self) -> list[Salon]:
        with self._connect(self.catalog_path) as db:
            rows = db.execute(
                "SELECT * FROM salons WHERE active=1 AND city=? ORDER BY name",
                (self.CITY,),
            ).fetchall()
        return [self._salon(row) for row in rows]

    def list_by_district(self, district: str) -> list[Salon]:
        if district not in DISTRICTS.values():
            return []
        with self._connect(self.catalog_path) as db:
            rows = db.execute(
                """SELECT * FROM salons
                   WHERE active=1 AND city=? AND district=? ORDER BY name""",
                (self.CITY, district),
            ).fetchall()
        return [self._salon(row) for row in rows]

    def search(self, query: str, district: str | None = None, limit: int = 8) -> list[Salon]:
        q = query.strip()[:80]
        if len(q) < 2 or (district is not None and district not in DISTRICTS.values()):
            return []
        needle = q.casefold()
        params: list[object] = [self.CITY, needle, needle + "\uffff"]
        district_sql = ""
        if district:
            district_sql = " AND salons.district=?"
            params.append(district)
        params.append(limit)
        with self._connect(self.catalog_path) as db:
            rows = db.execute(
                """SELECT DISTINCT salons.* FROM salons
                   JOIN search_terms ON search_terms.salon_id=salons.id
                   WHERE salons.active=1 AND salons.city=?
                     AND search_terms.term>=? AND search_terms.term<?"""
                + district_sql + " ORDER BY salons.name LIMIT ?",
                params,
            ).fetchall()
        return [self._salon(row) for row in rows]

    def get(self, user_id: int, chat_id: int) -> SessionState:
        with self._connect(self.catalog_path) as db:
            row = db.execute(
                "SELECT salon_id,district,mode FROM sessions WHERE user_id=? AND chat_id=?",
                (user_id, chat_id),
            ).fetchone()
        return SessionState(row["salon_id"], row["district"], row["mode"]) if row else SessionState()

    def set(self, user_id: int, chat_id: int, state: SessionState) -> None:
        with self._connect(self.catalog_path) as db:
            db.execute(
                """INSERT INTO sessions(user_id,chat_id,salon_id,district,mode) VALUES (?,?,?,?,?)
                   ON CONFLICT(user_id,chat_id) DO UPDATE SET
                     salon_id=excluded.salon_id, district=excluded.district, mode=excluded.mode""",
                (user_id, chat_id, state.salon_id, state.district, state.mode),
            )

    def relevant(self, salon_id: str, question: str, limit: int = 16) -> list[str]:
        if not self.by_id(salon_id):
            return []
        path = self._tenant_path(salon_id)
        if not path:
            return []
        tokens = re.findall(r"\w{3,}", question.casefold())[:12]
        with self._connect(path) as db:
            count = db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            if count <= limit:
                return [row["content"] for row in db.execute("SELECT content FROM facts ORDER BY id")]
            if tokens:
                query = " OR ".join('"' + token + '"' for token in tokens)
                rows = db.execute(
                    """SELECT facts.content FROM facts_fts
                       JOIN facts ON facts.id=facts_fts.rowid
                       WHERE facts_fts MATCH ? ORDER BY bm25(facts_fts) LIMIT ?""",
                    (query, limit),
                ).fetchall()
                if rows:
                    return [row["content"] for row in rows]
            rows = db.execute(
                "SELECT content FROM facts ORDER BY id LIMIT ?", (min(limit, 6),)
            ).fetchall()
            return [row["content"] for row in rows]

    def list_services(self, salon_id: str) -> list[ServiceItem]:
        if not self.by_id(salon_id):
            return []
        path = self._tenant_path(salon_id)
        if not path:
            return []
        self._ensure_tenant_schema(path)
        with self._connect(path) as db:
            rows = db.execute(
                "SELECT name,price FROM services ORDER BY sort_order,id"
            ).fetchall()
        return [ServiceItem(row["name"], row["price"]) for row in rows]
