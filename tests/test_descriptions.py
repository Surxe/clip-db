from clip_core import descriptions


def test_load_missing_file_is_empty(tmp_path):
    assert descriptions.load(tmp_path / "nope.json") == {}


def test_save_load_roundtrip_sorted(tmp_path):
    path = tmp_path / "descriptions.json"
    descriptions.save(path, {"b_clip": "second", "a_clip": "first"})
    # keys are written sorted for stable diffs
    assert path.read_text().index("a_clip") < path.read_text().index("b_clip")
    assert descriptions.load(path) == {"a_clip": "first", "b_clip": "second"}


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "descriptions.json"
    descriptions.save(path, {"x": "y"})
    assert descriptions.load(path) == {"x": "y"}
