"""SQLite access via aiosqlite. One connection, WAL mode, schema created on startup.

Schema changes: `CREATE TABLE IF NOT EXISTS` never adds columns to an existing table.
Add idempotent `ALTER TABLE ... ADD COLUMN` statements to MIGRATIONS for new columns.
"""
from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT NOT NULL DEFAULT 'Ahmad',
  level TEXT NOT NULL DEFAULT 'A1.1',
  unit_id TEXT NOT NULL DEFAULT 'a1.1-1',
  skills TEXT NOT NULL DEFAULT '{}',          -- json: speaking/listening/writing/grammar/vocab 0-100
  facts TEXT NOT NULL DEFAULT '[]',           -- json list of personal facts for conversation topics
  rolling_summary TEXT NOT NULL DEFAULT '',
  review_focus TEXT NOT NULL DEFAULT '[]',    -- json list set by a failed checkpoint
  placement_done INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mode TEXT NOT NULL,                         -- talk | placement | checkpoint
  scenario_id TEXT,
  scenario_title TEXT,
  unit_id TEXT,
  started_at REAL NOT NULL,
  ended_at REAL,
  summary TEXT NOT NULL DEFAULT '',
  analyzed_count INTEGER NOT NULL DEFAULT 0,  -- how many messages the analyzer has already seen
  user_turns INTEGER NOT NULL DEFAULT 0,
  meta TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  role TEXT NOT NULL,                         -- user | assistant
  content TEXT NOT NULL,
  transcript_raw TEXT,                        -- untouched STT output (user, voice)
  input_kind TEXT NOT NULL DEFAULT 'text',    -- text | voice
  correction TEXT,                            -- json (assistant turn: correction of previous user msg)
  english_help TEXT,                          -- json
  stt_provider TEXT,
  llm_model TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

CREATE TABLE IF NOT EXISTS mistakes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT NOT NULL,
  pattern TEXT NOT NULL,                      -- short description of the recurring error
  count INTEGER NOT NULL DEFAULT 1,
  resolved INTEGER NOT NULL DEFAULT 0,        -- correct drill answers in this category/pattern
  examples TEXT NOT NULL DEFAULT '[]',        -- json list of {wrong, right, note}
  first_seen REAL NOT NULL,
  last_seen REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mistakes_cat ON mistakes(category);

CREATE TABLE IF NOT EXISTS vocab (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  word TEXT NOT NULL UNIQUE,                  -- lemma incl. article for nouns, e.g. "der Termin"
  translation TEXT NOT NULL,
  example TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'manual',      -- manual | tutor | analyzer | writing
  created_at REAL NOT NULL,
  -- SM-2 state
  due REAL NOT NULL,
  interval_days REAL NOT NULL DEFAULT 0,
  ease REAL NOT NULL DEFAULT 2.5,
  reps INTEGER NOT NULL DEFAULT 0,
  lapses INTEGER NOT NULL DEFAULT 0,
  last_review REAL
);

CREATE TABLE IF NOT EXISTS vocab_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vocab_id INTEGER NOT NULL REFERENCES vocab(id) ON DELETE CASCADE,
  rating INTEGER NOT NULL,                    -- 1 again, 2 hard, 3 good, 4 easy
  reviewed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS translations (
  word TEXT PRIMARY KEY,                      -- lowercase surface form
  data TEXT NOT NULL,                         -- json from the translate prompt
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS writings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  unit_id TEXT,
  prompt TEXT NOT NULL,
  text TEXT NOT NULL,
  feedback TEXT NOT NULL,                     -- json
  score INTEGER,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS drills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  categories TEXT NOT NULL,                   -- json list
  items TEXT NOT NULL,                        -- json list
  answers TEXT,                               -- json list (user answers)
  results TEXT,                               -- json list (graded)
  score INTEGER,
  created_at REAL NOT NULL,
  finished_at REAL
);

CREATE TABLE IF NOT EXISTS checkpoints (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  unit_id TEXT NOT NULL,
  tasks TEXT NOT NULL,                        -- json {speaking:{...}, writing:{...}}
  speaking_transcript TEXT,
  writing_text TEXT,
  result TEXT,                                -- json grading
  passed INTEGER,
  created_at REAL NOT NULL,
  finished_at REAL
);

CREATE TABLE IF NOT EXISTS activity (
  day TEXT NOT NULL,                          -- YYYY-MM-DD, UTC
  kind TEXT NOT NULL,                         -- talk_turn | review | drill | write | checkpoint
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, kind)
);
"""

# (table, column, definition) — applied only when the column is missing.
MIGRATIONS: list[tuple[str, str, str]] = [
    ("messages", "audio_path", "TEXT"),   # a voice turn's recording, kept until the analyzer has heard it
]

DEFAULT_SKILLS = {"speaking": 10, "listening": 10, "writing": 10, "grammar": 10, "vocab": 10}


class Database:
    def __init__(self) -> None:
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "database not connected"
        return self._conn

    async def connect(self) -> None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.audio_dir.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(settings.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)
        for table, column, definition in MIGRATIONS:
            cols = [r["name"] for r in await self.fetchall(f"PRAGMA table_info({table})")]
            if column not in cols:
                await self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        now = time.time()
        await self._conn.execute(
            "INSERT OR IGNORE INTO profile (id, skills, created_at, updated_at) VALUES (1, ?, ?, ?)",
            (json.dumps(DEFAULT_SKILLS), now, now),
        )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # -- small helpers ---------------------------------------------------
    async def fetchone(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        cur = await self.conn.execute(sql, params)
        row = await cur.fetchone()
        return dict(row) if row else None

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        cur = await self.conn.execute(sql, params)
        return [dict(r) for r in await cur.fetchall()]

    async def execute(self, sql: str, params: tuple = ()) -> int:
        """Run one statement and commit. Returns lastrowid."""
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur.lastrowid or 0

    async def kv_get(self, key: str, default: str | None = None) -> str | None:
        row = await self.fetchone("SELECT value FROM kv WHERE key=?", (key,))
        return row["value"] if row else default

    async def kv_set(self, key: str, value: str) -> None:
        await self.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    async def bump_activity(self, kind: str, n: int = 1) -> None:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        await self.execute(
            "INSERT INTO activity (day, kind, count) VALUES (?, ?, ?) "
            "ON CONFLICT(day, kind) DO UPDATE SET count = count + excluded.count",
            (day, kind, n),
        )


db = Database()


def loads(s: str | None, default: Any) -> Any:
    """json.loads that tolerates NULL/garbage columns."""
    if not s:
        return default
    try:
        return json.loads(s)
    except ValueError:
        return default
