"""SQLite storage for scrape runs, their items and messages, plus a page cache.

Every query uses parameters (never string formatting), so scraped text can
never be interpreted as SQL. The profile used for a run is stored with it,
so old runs can still be analysed after a profile changes.
"""

import json
import sqlite3
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .exceptions import StorageError, ValidationError
from .fetcher import Page
from .profiles import load_profile

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile     TEXT    NOT NULL,
    profile_json TEXT   NOT NULL,
    start_url   TEXT    NOT NULL,
    mode        TEXT    NOT NULL,
    started     TEXT    NOT NULL,
    finished    TEXT,
    duration    REAL,
    status      TEXT    NOT NULL,
    pages       INTEGER NOT NULL,
    items       INTEGER NOT NULL,
    duplicates  INTEGER NOT NULL DEFAULT 0,
    stop_reason TEXT,
    units_json  TEXT    NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS items (
    run_id    INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    data_json TEXT    NOT NULL,
    PRIMARY KEY (run_id, position)
);
CREATE TABLE IF NOT EXISTS messages (
    run_id  INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    level   TEXT    NOT NULL CHECK (level IN ('warning', 'error')),
    message TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS run_pages (
    run_id     INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL,
    url        TEXT    NOT NULL,
    status     INTEGER,
    items      INTEGER,
    from_cache INTEGER,
    elapsed    REAL
);
CREATE TABLE IF NOT EXISTS page_cache (
    url          TEXT PRIMARY KEY,
    final_url    TEXT    NOT NULL,
    status       INTEGER NOT NULL,
    content_type TEXT    NOT NULL,
    body         TEXT    NOT NULL,
    size         INTEGER NOT NULL,
    fetched      REAL    NOT NULL
);
"""


@dataclass
class Run:
    id: int
    profile: object
    start_url: str
    mode: str
    started: str
    finished: str
    duration: float
    status: str
    duplicates: int
    stop_reason: str
    units: dict
    items: list = field(default_factory=list)
    pages: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)  # exact: never round-trip money through float
    raise TypeError(f"Cannot store {type(value).__name__} values")


def _encode(item):
    return json.dumps(item, ensure_ascii=False, default=_json_default)


def _decode(data, profile):
    item = json.loads(data)
    for f in profile.fields.values():
        value = item.get(f.name)
        if value is None:
            continue
        if f.type in ("number", "money", "rating"):
            item[f.name] = Decimal(str(value))
        elif f.type == "count":
            item[f.name] = int(value)
    return item


class Database:
    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self._clock = clock
        self.conn = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.path)
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.executescript(SCHEMA)
        except sqlite3.DatabaseError as exc:
            if self.conn is not None:
                self.conn.close()  # release the file so it can be renamed or deleted
            raise StorageError(f"{self.path} is not a usable database ({exc}). "
                               "Rename or delete it and a new one will be created.") from None
        except OSError as exc:
            raise StorageError(f"Could not open the database: {exc}") from None

    def close(self):
        if self.conn is not None:
            self.conn.close()

    def _execute(self, sql, params=()):
        try:
            return self.conn.execute(sql, params)
        except sqlite3.DatabaseError as exc:
            raise StorageError(f"Database error: {exc}") from None

    # ------------------------------------------------------------ runs
    def save_run(self, result, mode="live"):
        p = result.profile
        try:
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO runs (profile, profile_json, start_url, mode, started, finished, duration, status,"
                    " pages, items, duplicates, stop_reason, units_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (p.name, json.dumps(p.raw), result.start_url, mode, result.started, result.finished,
                     result.duration, result.status, len(result.pages), len(result.items), result.duplicates,
                     result.stop_reason, json.dumps(result.units, ensure_ascii=False)))
                run_id = cur.lastrowid
                self.conn.executemany("INSERT INTO items (run_id, position, data_json) VALUES (?,?,?)",
                                      [(run_id, i, _encode(item)) for i, item in enumerate(result.items, 1)])
                self.conn.executemany("INSERT INTO messages (run_id, level, message) VALUES (?,?,?)",
                                      [(run_id, "warning", m) for m in result.warnings]
                                      + [(run_id, "error", m) for m in result.errors])
                self.conn.executemany(
                    "INSERT INTO run_pages (run_id, position, url, status, items, from_cache, elapsed)"
                    " VALUES (?,?,?,?,?,?,?)",
                    [(run_id, i, pg.url, pg.status, pg.items, int(pg.from_cache), pg.elapsed)
                     for i, pg in enumerate(result.pages, 1)])
        except sqlite3.DatabaseError as exc:
            raise StorageError(f"Could not save the run: {exc}") from None
        return run_id

    def list_runs(self, limit=20, profile=None):
        sql = ("SELECT id, profile, start_url, mode, started, status, pages, items, duplicates, duration "
               "FROM runs {} ORDER BY id DESC LIMIT ?")
        params = (profile, limit) if profile else (limit,)
        rows = self._execute(sql.format("WHERE profile = ?" if profile else ""), params).fetchall()
        cols = ("id", "profile", "start_url", "mode", "started", "status", "pages", "items", "duplicates", "duration")
        return [dict(zip(cols, row)) for row in rows]

    def get_run(self, run_id):
        try:
            run_id = int(str(run_id).strip())
        except ValueError:
            raise ValidationError("Run number must be a whole number.") from None
        row = self._execute("SELECT id, profile_json, start_url, mode, started, finished, duration, status,"
                            " duplicates, stop_reason, units_json FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise ValidationError(f"There is no run #{run_id}. Use 'Run history' to see the saved runs.")
        profile = load_profile(json.loads(row[1]))
        run = Run(row[0], profile, row[2], row[3], row[4], row[5] or "", row[6] or 0.0, row[7], row[8],
                  row[9] or "", json.loads(row[10] or "{}"))
        run.items = [_decode(d, profile) for (d,) in self._execute(
            "SELECT data_json FROM items WHERE run_id = ? ORDER BY position", (run_id,))]
        for level, message in self._execute("SELECT level, message FROM messages WHERE run_id = ?", (run_id,)):
            (run.errors if level == "error" else run.warnings).append(message)
        run.pages = [dict(zip(("url", "status", "items", "from_cache", "elapsed"), r)) for r in self._execute(
            "SELECT url, status, items, from_cache, elapsed FROM run_pages WHERE run_id = ? ORDER BY position",
            (run_id,))]
        return run

    def latest_run_ids(self, profile, n=2):
        return [r[0] for r in self._execute("SELECT id FROM runs WHERE profile = ? ORDER BY id DESC LIMIT ?",
                                            (profile, n))]

    def delete_run(self, run_id):
        run = self.get_run(run_id)
        with self.conn:
            self.conn.execute("DELETE FROM runs WHERE id = ?", (run.id,))
        return run.id

    # ------------------------------------------------------------ page cache
    def get_page(self, url, max_age):
        row = self._execute("SELECT final_url, status, content_type, body, size, fetched FROM page_cache "
                            "WHERE url = ?", (url,)).fetchone()
        if row is None or self._clock() - row[5] > max_age:
            return None
        return Page(row[0], row[1], row[2], row[3], 0.0, row[4], from_cache=True)

    def put_page(self, url, page):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO page_cache (url, final_url, status, content_type, body, size,"
                              " fetched) VALUES (?,?,?,?,?,?,?)",
                              (url, page.url, page.status, page.content_type, page.text, page.size, self._clock()))

    def clear_cache(self):
        with self.conn:
            return self.conn.execute("DELETE FROM page_cache").rowcount

    def cache_size(self):
        return self._execute("SELECT COUNT(*) FROM page_cache").fetchone()[0]
