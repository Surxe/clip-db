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
    tags        TEXT NOT NULL DEFAULT ''   -- comma-separated, normalized
);
CREATE INDEX IF NOT EXISTS idx_clips_game ON clips(game);
"""


def connect(index_path) -> sqlite3.Connection:
    p = Path(index_path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
