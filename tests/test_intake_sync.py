"""Mirror step: copy new masters from a read-only source into intake, skipping ones
already ingested (in library) or already staged (in intake). The source is never mutated."""
import os
import stat

import pytest

from clip_core import media
from clip_core.config import Config
from clip_core.intake_sync import sync_intake


def _clip(path):
    path.write_bytes(b"\x00")


def _cfg(tmp_path, *, source):
    return Config(
        intake_dir=tmp_path / "intake",
        library_dir=tmp_path / "library",
        index_path=tmp_path / "index.sqlite",
        tags_path=tmp_path / "tags.json",
        aliases_path=tmp_path / "a.json",
        implications_path=tmp_path / "i.json",
        descriptions_path=tmp_path / "intake" / "descriptions.json",
        discord_queue_dir=tmp_path / "q",
        model="claude-test",
        embed_model="all-MiniLM-L6-v2",
        semantic_top_k=5,
        auto_merge_max_seconds=120,
        source_dir=source,
    )


def test_copies_new_masters_only(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _clip(source / "a.mp4")
    _clip(source / "b.mp4")
    cfg = _cfg(tmp_path, source=source)

    copied = sync_intake(cfg, verbose=False)

    assert {p.name for p in copied} == {"a.mp4", "b.mp4"}
    assert (cfg.intake_dir / "a.mp4").exists()
    assert (cfg.intake_dir / "b.mp4").exists()


def test_skips_already_ingested_in_library(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _clip(source / "a.mp4")
    _clip(source / "b.mp4")
    cfg = _cfg(tmp_path, source=source)
    cfg.library_dir.mkdir()
    _clip(cfg.library_dir / "a.mp4")  # a already ingested

    copied = sync_intake(cfg, verbose=False)

    assert {p.name for p in copied} == {"b.mp4"}
    assert not (cfg.intake_dir / "a.mp4").exists()  # not re-copied


def test_skips_already_staged_in_intake(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _clip(source / "a.mp4")
    cfg = _cfg(tmp_path, source=source)
    cfg.intake_dir.mkdir()
    _clip(cfg.intake_dir / "a.mp4")  # already staged, awaiting ingest

    copied = sync_intake(cfg, verbose=False)

    assert copied == []


def test_ignores_merged_as_master_but_carries_sibling(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _clip(source / "a.mp4")
    _clip(source / "a_merged.mp4")  # rendition that rides along with its master
    cfg = _cfg(tmp_path, source=source)

    copied = sync_intake(cfg, verbose=False)

    assert {p.name for p in copied} == {"a.mp4"}  # merged is not a master
    assert (cfg.intake_dir / "a_merged.mp4").exists()  # but it was carried along


def test_source_is_never_written(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _clip(source / "a.mp4")
    cfg = _cfg(tmp_path, source=source)
    source.chmod(stat.S_IRUSR | stat.S_IXUSR)  # read-only dir: no create/delete allowed
    try:
        copied = sync_intake(cfg, verbose=False)
    finally:
        source.chmod(stat.S_IRWXU)

    assert {p.name for p in copied} == {"a.mp4"}
    assert {p.name for p in source.iterdir()} == {"a.mp4"}  # source untouched


def test_dry_run_copies_nothing(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _clip(source / "a.mp4")
    cfg = _cfg(tmp_path, source=source)

    copied = sync_intake(cfg, dry_run=True, verbose=False)

    assert {p.name for p in copied} == {"a.mp4"}
    assert not (cfg.intake_dir / "a.mp4").exists()


def test_noop_when_source_unset(tmp_path):
    cfg = _cfg(tmp_path, source=None)
    assert sync_intake(cfg, verbose=False) == []


def test_noop_when_source_equals_intake(tmp_path):
    intake = tmp_path / "intake"
    intake.mkdir()
    _clip(intake / "a.mp4")
    cfg = _cfg(tmp_path, source=intake)
    assert sync_intake(cfg, verbose=False) == []
