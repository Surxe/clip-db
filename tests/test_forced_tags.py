"""Forced tags manifest: batch-wide ("*") plus per-stem, normalized and merged."""
from clip_core import forced_tags


def test_load_normalizes_and_dedupes(tmp_path):
    p = tmp_path / "forced_tags.json"
    p.write_text('{"*": ["War Robots Frontiers", "war robots frontiers", "  Clutch  "]}')
    m = forced_tags.load(p)
    assert m["*"] == ["war robots frontiers", "clutch"]


def test_load_absent_is_empty(tmp_path):
    assert forced_tags.load(tmp_path / "nope.json") == {}


def test_for_stem_combines_batch_and_per_stem(tmp_path):
    m = {"*": ["war robots frontiers"], "clip1": ["clutch", "war robots frontiers"]}
    assert forced_tags.for_stem(m, "clip1") == ["war robots frontiers", "clutch"]
    assert forced_tags.for_stem(m, "other") == ["war robots frontiers"]


def test_save_roundtrip_sorted(tmp_path):
    p = tmp_path / "forced_tags.json"
    forced_tags.save(p, {"z": ["a"], "*": ["war robots frontiers"]})
    assert list(forced_tags.load(p)) == ["*", "z"]
