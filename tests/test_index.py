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
        tags=["clutch", "valorant"],
    )
    index.upsert_clip(conn, clip)

    got = index.get_clip(conn, "clip123")
    assert got is not None
    assert got.master_path == "/lib/clip123.mp4"
    assert got.merged_path == "/lib/clip123_merged.mp4"
    assert got.game == "valorant"
    assert got.duration == 12.5
    assert got.tags == ["clutch", "valorant"]


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
