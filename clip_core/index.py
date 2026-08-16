"""Index operations over the clips table."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .tags import normalize


@dataclass
class Clip:
    stem: str
    master_path: str
    merged_path: str | None = None
    game: str | None = None
    date: str | None = None
    duration: float | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)


def _tags_to_str(tags: list[str]) -> str:
    return ",".join(dict.fromkeys(normalize(t) for t in tags if t.strip()))


def _tags_to_list(s: str | None) -> list[str]:
    return [t for t in (s or "").split(",") if t]


def _row_to_clip(row: sqlite3.Row) -> Clip:
    return Clip(
        stem=row["stem"],
        master_path=row["master_path"],
        merged_path=row["merged_path"],
        game=row["game"],
        date=row["date"],
        duration=row["duration"],
        description=row["description"],
        tags=_tags_to_list(row["tags"]),
    )


def upsert_clip(conn: sqlite3.Connection, clip: Clip) -> None:
    conn.execute(
        """INSERT INTO clips(stem, master_path, merged_path, game, date, duration, description, tags)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(stem) DO UPDATE SET
             master_path=excluded.master_path,
             merged_path=excluded.merged_path,
             game=excluded.game,
             date=excluded.date,
             duration=excluded.duration,
             description=excluded.description,
             tags=excluded.tags""",
        (
            clip.stem,
            clip.master_path,
            clip.merged_path,
            clip.game,
            clip.date,
            clip.duration,
            clip.description,
            _tags_to_str(clip.tags),
        ),
    )
    conn.commit()


def get_clip(conn: sqlite3.Connection, stem: str) -> Clip | None:
    row = conn.execute("SELECT * FROM clips WHERE stem=?", (stem,)).fetchone()
    return _row_to_clip(row) if row else None


def all_clips(conn: sqlite3.Connection) -> list[Clip]:
    rows = conn.execute("SELECT * FROM clips ORDER BY stem").fetchall()
    return [_row_to_clip(r) for r in rows]


def list_untagged(conn: sqlite3.Connection) -> list[Clip]:
    rows = conn.execute(
        "SELECT * FROM clips WHERE tags='' OR tags IS NULL ORDER BY stem"
    ).fetchall()
    return [_row_to_clip(r) for r in rows]


def set_tags(conn: sqlite3.Connection, stem: str, tags: list[str]) -> None:
    conn.execute("UPDATE clips SET tags=? WHERE stem=?", (_tags_to_str(tags), stem))
    conn.commit()


def add_tag(conn: sqlite3.Connection, stem: str, tag: str) -> None:
    clip = get_clip(conn, stem)
    if clip is None:
        raise KeyError(stem)
    t = normalize(tag)
    if t and t not in clip.tags:
        clip.tags.append(t)
        set_tags(conn, stem, clip.tags)
