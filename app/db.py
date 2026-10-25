"""SQLite access via aiosqlite. One connection, WAL mode, schema created on startup.

Two learners share the file: every learner table carries `user_id`, and services always filter on
the current user (`app.users.user_id()`). `translations` and `kv` are the only shared tables.

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

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,              -- login name, lowercase
  name TEXT NOT NULL,                         -- display name
  gender TEXT NOT NULL DEFAULT 'x',           -- m | f | x: the tutor needs it for German forms
  about TEXT NOT NULL DEFAULT '',             -- the paragraph the tutor is told (personas.json)
  avatar TEXT NOT NULL DEFAULT 'katze-1',     -- one of the mascot variants
  password_hash TEXT,                         -- pbkdf2, set from USER_<NAME>_PASSWORD; never clear text
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS profile (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
  name TEXT NOT NULL DEFAULT '',
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
  user_id INTEGER NOT NULL REFERENCES users(id),
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
  user_id INTEGER NOT NULL REFERENCES users(id),
  category TEXT NOT NULL,
  pattern TEXT NOT NULL,                      -- short description of the recurring error
  count INTEGER NOT NULL DEFAULT 1,
  resolved INTEGER NOT NULL DEFAULT 0,        -- correct drill answers in this category/pattern
  examples TEXT NOT NULL DEFAULT '[]',        -- json list of {wrong, right, note}
  first_seen REAL NOT NULL,
  last_seen REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mistakes_cat ON mistakes(user_id, category);

CREATE TABLE IF NOT EXISTS vocab (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  word TEXT NOT NULL,                         -- lemma incl. article for nouns, e.g. "der Termin"
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
  last_review REAL,
  UNIQUE (user_id, word)
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
  user_id INTEGER NOT NULL REFERENCES users(id),
  unit_id TEXT,
  prompt TEXT NOT NULL,
  text TEXT NOT NULL,
  feedback TEXT NOT NULL,                     -- json
  score INTEGER,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS drills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
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
  user_id INTEGER NOT NULL REFERENCES users(id),
  unit_id TEXT NOT NULL,
  tasks TEXT NOT NULL,                        -- json {speaking:{...}, writing:{...}}
  speaking_transcript TEXT,
  writing_text TEXT,
  result TEXT,                                -- json grading
  passed INTEGER,
  created_at REAL NOT NULL,
  finished_at REAL
);

CREATE TABLE IF NOT EXISTS lesson_progress (
  user_id INTEGER NOT NULL REFERENCES users(id),
  unit_id TEXT NOT NULL,                      -- matches curriculum/units.json
  step INTEGER NOT NULL DEFAULT 0,            -- furthest step reached, so he resumes where he stopped
  completed INTEGER NOT NULL DEFAULT 0,
  checks_right INTEGER NOT NULL DEFAULT 0,
  checks_total INTEGER NOT NULL DEFAULT 0,
  started_at REAL,
  completed_at REAL,
  PRIMARY KEY (user_id, unit_id)
);

CREATE TABLE IF NOT EXISTS activity (
  user_id INTEGER NOT NULL REFERENCES users(id),
  day TEXT NOT NULL,                          -- YYYY-MM-DD, UTC
  kind TEXT NOT NULL,                         -- talk_turn | review | drill | write | checkpoint | lesson
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, day, kind)
);

CREATE TABLE IF NOT EXISTS badges (
  user_id INTEGER NOT NULL REFERENCES users(id),
  badge_id TEXT NOT NULL,                     -- catalogue in app/services/game.py
  earned_at REAL NOT NULL,
  seen INTEGER NOT NULL DEFAULT 0,            -- 0 until the client has shown the moment once
  PRIMARY KEY (user_id, badge_id)
);
"""

# (table, column, definition) — applied only when the column is missing.
MIGRATIONS: list[tuple[str, str, str]] = [
    ("messages", "audio_path", "TEXT"),   # a voice turn's recording, kept until the analyzer has heard it
    # The tutor speaks German; this is what it means. A beginner cannot bootstrap from German alone,
    # so the meaning travels with every reply instead of costing a second model call to ask for.
    ("messages", "meaning_en", "TEXT"),
    # The tutor talking to a beginner in English: an explanation or what to say next (by level).
    ("messages", "coach_en", "TEXT"),
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
        await self._conn.commit()
        # A database from the single-learner version has no user_id anywhere. It cannot be migrated
        # in place (every row would need an owner), and the owner asked for a clean start anyway.
        profile_cols = [r["name"] for r in await self.fetchall("PRAGMA table_info(profile)")]
        if "user_id" not in profile_cols:
            raise RuntimeError(
                f"{settings.db_path} is from the single-learner version and cannot be upgraded in place. "
                "On the server: bash deploy/backup.sh; docker compose down; "
                "rm -f data/tutor.db data/tutor.db-wal data/tutor.db-shm; rm -rf data/audio; "
                "bash deploy/deploy.sh (README.md, 'Upgrading from the single-learner version'). "
                "Locally: .venv/bin/python scripts/reset_data.py")
        # Accounts and their profile rows are created by app.users.seed(), after connect().

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

    async def bump_activity(self, kind: str, n: int = 1, user_id: int | None = None) -> None:
        """Per-day, per-user counters: the progress page, the streak and the XP all derive from them."""
        if user_id is None:
            from .users import user_id as current_user_id  # late import: users imports db
            user_id = current_user_id()
        day = time.strftime("%Y-%m-%d", time.gmtime())
        await self.execute(
            "INSERT INTO activity (user_id, day, kind, count) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, day, kind) DO UPDATE SET count = count + excluded.count",
            (user_id, day, kind, n),
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
