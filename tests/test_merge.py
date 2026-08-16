"""Merge orchestration: attach a _merged.mp4 to the right asset row, idempotently.

ffmpeg is stubbed (monkeypatch on media.regenerate_merged just touches the out file), so
the test exercises the real pairing/index/idempotency logic without encoding anything."""
import pytest

from clip_core import index, media, merge
from clip_core.schema import connect


@pytest.fixture
def conn():
    return connect(":memory:")


@pytest.fixture(autouse=True)
def stub_ffmpeg(monkeypatch):
    def fake_regen(master, out):
        from pathlib import Path
        Path(out).write_bytes(b"merged")
        return Path(out)
    monkeypatch.setattr(media, "regenerate_merged", fake_regen)


def _add(conn, tmp_path, stem, duration, *, merged=False):
    master = tmp_path / f"{stem}.mp4"
    master.write_bytes(b"\x00")
    merged_path = None
    if merged:
        mp = tmp_path / media.merged_name_for(master)
        mp.write_bytes(b"merged")
        merged_path = str(mp)
    index.upsert_clip(conn, index.Clip(
        stem=stem, master_path=str(master), merged_path=merged_path,
        duration=duration, tags=["clutch"], description="a play",
    ))
    return master


def test_set_merged_path_updates_without_clobbering(conn, tmp_path):
    _add(conn, tmp_path, "a", 30)
    assert index.set_merged_path(conn, "a", "/lib/a_merged.mp4") is True
    clip = index.get_clip(conn, "a")
    assert clip.merged_path == "/lib/a_merged.mp4"
    assert clip.tags == ["clutch"]          # untouched
    assert clip.description == "a play"     # untouched
    assert index.set_merged_path(conn, "missing", "x") is False


def test_merge_master_creates_and_attaches(conn, tmp_path):
    master = _add(conn, tmp_path, "a", 30)
    r = merge.merge_master(conn, master)
    assert r.status == merge.CREATED
    assert (tmp_path / "a_merged.mp4").exists()
    assert index.get_clip(conn, "a").merged_path == str(tmp_path / "a_merged.mp4")


def test_merge_master_skips_when_present(conn, tmp_path):
    master = _add(conn, tmp_path, "a", 30, merged=True)
    r = merge.merge_master(conn, master)
    assert r.status == merge.SKIPPED_EXISTS


def test_merge_master_force_regenerates(conn, tmp_path):
    master = _add(conn, tmp_path, "a", 30, merged=True)
    r = merge.merge_master(conn, master, force=True)
    assert r.status == merge.CREATED


def test_merge_master_not_indexed(conn, tmp_path):
    master = tmp_path / "loose.mp4"
    master.write_bytes(b"\x00")
    r = merge.merge_master(conn, master)
    assert r.status == merge.NOT_INDEXED
    assert (tmp_path / "loose_merged.mp4").exists()  # file still written


def test_merge_master_resolves_merged_input(conn, tmp_path):
    _add(conn, tmp_path, "a", 30)
    r = merge.merge_master(conn, tmp_path / "a_merged.mp4")  # pass the merged name
    assert r.stem == "a"
    assert r.status == merge.CREATED


def test_sweep_short_filters_and_is_idempotent(conn, tmp_path):
    _add(conn, tmp_path, "short", 28)
    _add(conn, tmp_path, "long", 664)
    _add(conn, tmp_path, "premerged", 40, merged=True)

    results = {r.stem: r.status for r in merge.sweep_short(conn, max_seconds=120)}
    assert results == {"short": merge.CREATED}          # long excluded, premerged skipped

    # second run: short now has a merged rendition -> clean no-op
    assert merge.sweep_short(conn, max_seconds=120) == []
