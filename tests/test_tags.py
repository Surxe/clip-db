import json

from clip_core.tags import TagVocab, load_vocab


def test_normalize_and_dedupe(tmp_path):
    p = tmp_path / "tags.json"
    p.write_text(json.dumps({"tags": ["Clutch", " fail ", "clutch", "ace"]}))
    v = load_vocab(p)
    assert "clutch" in v
    assert "FAIL" in v  # membership is normalized
    assert "missing" not in v
    assert v.as_list() == ["clutch", "fail", "ace"]
    assert len(v) == 3


def test_accepts_bare_list():
    v = TagVocab(["highlight", "funny"])
    assert list(v) == ["highlight", "funny"]
