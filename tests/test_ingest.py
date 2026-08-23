"""Ingest wiring: manifest -> batch classify -> move + index. The classifier and duration
probe are stubbed so the test is hermetic (no `claude` CLI, no ffprobe), but the real
pairing/move/upsert code runs against temp dirs."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from clip_core import descriptions, index, media
from clip_core.classify import Classification
from clip_core.config import Config
from clip_core.schema import connect

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_ingest():
    spec = importlib.util.spec_from_file_location("ingest_mod", REPO_ROOT / "clip-tagger" / "ingest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_clip(path: Path):
    path.write_bytes(b"\x00")  # a stand-in file; probe is stubbed


@pytest.fixture
def env(tmp_path, monkeypatch):
    intake = tmp_path / "intake"
    library = tmp_path / "library"
    intake.mkdir()
    _make_clip(intake / "a.mp4")
    _make_clip(intake / "a_merged.mp4")  # pair for a
    _make_clip(intake / "b.mp4")
    _make_clip(intake / "c.mp4")         # undescribed

    tags_path = tmp_path / "tags.json"
    tags_path.write_text(json.dumps({"generic": ["clutch"], "games": {}}))
    desc_path = intake / "descriptions.json"
    descriptions.save(desc_path, {"a": "1v4 retake", "b": "threw the game"})

    cfg = Config(
        intake_dir=intake,
        library_dir=library,
        index_path=tmp_path / "index.sqlite",
        tags_path=tags_path,
        aliases_path=tmp_path / "tag_aliases.json",
        implications_path=tmp_path / "tag_implications.json",
        descriptions_path=desc_path,
        discord_queue_dir=tmp_path / "discord-queue",
        model="claude-test",
        auto_merge_max_seconds=120,
    )
    mod = _load_ingest()
    monkeypatch.setattr(mod, "load_config", lambda: cfg)
    monkeypatch.setattr(media, "probe_duration", lambda p: 12.0)

    def _fake_regen(master_path, out_path=None):  # stand in for ffmpeg
        out = Path(out_path) if out_path else Path(master_path).with_name(media.merged_name_for(master_path))
        out.write_bytes(b"\x00")
        return out

    monkeypatch.setattr(media, "regenerate_merged", _fake_regen)
    monkeypatch.setattr(
        mod,
        "llm_classify_batch",
        lambda items, vocab, relations=None, model=None: {
            "a": Classification(tags=["clutch"], proposed_tag=None),
            "b": Classification(tags=[], proposed_tag="meltdown"),
        },
    )
    monkeypatch.setattr(sys, "argv", ["ingest.py"])
    return mod, cfg, intake, library


def test_ingest_moves_pairs_and_indexes(env):
    mod, cfg, intake, library = env
    mod.main()

    conn = connect(cfg.index_path)
    a = index.get_clip(conn, "a")
    assert a.tags == ["clutch"]
    assert a.description == "1v4 retake"
    assert a.master_path == str(library / "a.mp4")
    assert a.merged_path == str(library / "a_merged.mp4")  # merged paired + moved
    assert not (intake / "a.mp4").exists()                 # master left staging

    # a already brought its own _merged.mp4 -> not regenerated (no stray extra file)
    assert media.regenerate_merged  # sanity: stub is installed

    # b had no merged and is short -> ingest generated + attached one in the library
    b = index.get_clip(conn, "b")
    assert b.tags == []
    assert b.merged_path == str(library / "b_merged.mp4")
    assert (library / "b_merged.mp4").exists()

    # b had a proposed tag -> written to proposals.json, no tags yet
    proposals = json.loads((cfg.index_path.parent / "proposals.json").read_text())
    assert proposals == {"b": "meltdown"}


def test_ingest_skips_undescribed(env):
    mod, cfg, intake, library = env
    mod.main()
    conn = connect(cfg.index_path)
    assert index.get_clip(conn, "c") is None        # not ingested
    assert (intake / "c.mp4").exists()              # left in staging


def test_no_merge_skips_generation(env, monkeypatch):
    mod, cfg, intake, library = env
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--no-merge"])
    mod.main()
    conn = connect(cfg.index_path)
    assert index.get_clip(conn, "b").merged_path is None   # not generated
    assert not (library / "b_merged.mp4").exists()


def test_long_master_not_auto_merged(env, monkeypatch):
    mod, cfg, intake, library = env
    monkeypatch.setattr(media, "probe_duration", lambda p: 999.0)  # over threshold
    mod.main()
    conn = connect(cfg.index_path)
    assert index.get_clip(conn, "b").merged_path is None   # too long -> skipped
    assert not (library / "b_merged.mp4").exists()


def test_dry_run_moves_nothing(env, monkeypatch):
    mod, cfg, intake, library = env
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--dry-run"])
    mod.main()
    assert (intake / "a.mp4").exists()              # nothing moved
    assert not library.exists() or not any(library.iterdir())
    assert not (cfg.index_path.parent / "proposals.json").exists()
