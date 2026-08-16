"""SQLite schema and connection helper. One row per asset (not per file)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    stem        TEXT PRIMARY KEY,          -- asset id, e.g. "clip123"
    master_path TEXT NOT NULL,             -- split-audio original (source of truth)
    merged_path TEXT,                      -- regenerable _merged.mp4 (nullable)
    game        TEXT,
    date        TEXT,
    duration    REAL,
    description TEXT,                       -- the one-line source description (nullable)
    tags        TEXT NOT NULL DEFAULT ''   -- comma-separated, normalized
);
CREATE INDEX IF NOT EXISTS idx_clips_game ON clips(game);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for indexes created before a column existed.

    CREATE TABLE IF NOT EXISTS never alters an existing table, so a pre-existing
    index.sqlite needs the column added explicitly. Idempotent: only adds what's missing.
    """
    have = {row["name"] for row in conn.execute("PRAGMA table_info(clips)")}
    if "description" not in have:
        conn.execute("ALTER TABLE clips ADD COLUMN description TEXT")
        conn.commit()


def connect(index_path) -> sqlite3.Connection:
    p = Path(index_path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn
