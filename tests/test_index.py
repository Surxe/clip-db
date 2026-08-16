import sqlite3

from clip_core import index
from clip_core.schema import connect


def test_upsert_and_get_roundtrip():
    conn = connect(":memory:")
    clip = index.Clip(
        stem="clip123",
        master_path="/lib/clip123.mp4",
        merged_path="/lib/clip123_merged.mp4",
        game="valorant",
        date="2026-08-04",
        duration=12.5,
        description="1v4 retake for the round",
        tags=["clutch", "valorant"],
    )
    index.upsert_clip(conn, clip)

    got = index.get_clip(conn, "clip123")
    assert got is not None
    assert got.master_path == "/lib/clip123.mp4"
    assert got.merged_path == "/lib/clip123_merged.mp4"
    assert got.game == "valorant"
    assert got.duration == 12.5
    assert got.description == "1v4 retake for the round"
    assert got.tags == ["clutch", "valorant"]


def test_migration_adds_description_to_legacy_table(tmp_path):
    """A pre-existing index without the description column gets it added on connect."""
    db = tmp_path / "legacy.sqlite"
    raw = sqlite3.connect(db)
    raw.executescript(
        """CREATE TABLE clips (
               stem TEXT PRIMARY KEY, master_path TEXT NOT NULL, merged_path TEXT,
               game TEXT, date TEXT, duration REAL, tags TEXT NOT NULL DEFAULT ''
           );"""
    )
    raw.execute("INSERT INTO clips(stem, master_path, tags) VALUES('old', '/old.mp4', 'clutch')")
    raw.commit()
    raw.close()

    conn = connect(db)  # runs the migration
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(clips)")}
    assert "description" in cols
    got = index.get_clip(conn, "old")
    assert got.description is None
    assert got.tags == ["clutch"]

    index.upsert_clip(conn, index.Clip(stem="old", master_path="/old.mp4", description="now described"))
    assert index.get_clip(conn, "old").description == "now described"


def test_upsert_is_idempotent_on_stem():
    conn = connect(":memory:")
    index.upsert_clip(conn, index.Clip(stem="a", master_path="/a.mp4", tags=["fail"]))
    index.upsert_clip(conn, index.Clip(stem="a", master_path="/a2.mp4", tags=["funny"]))
    got = index.get_clip(conn, "a")
    assert got.master_path == "/a2.mp4"
    assert got.tags == ["funny"]
    assert len(index.all_clips(conn)) == 1


def test_untagged_and_add_tag():
    conn = connect(":memory:")
    index.upsert_clip(conn, index.Clip(stem="a", master_path="/a.mp4"))
    assert [c.stem for c in index.list_untagged(conn)] == ["a"]

    index.add_tag(conn, "a", "Funny")  # normalized on the way in
    assert index.get_clip(conn, "a").tags == ["funny"]
    assert index.list_untagged(conn) == []

    index.add_tag(conn, "a", "funny")  # no duplicate
    assert index.get_clip(conn, "a").tags == ["funny"]
