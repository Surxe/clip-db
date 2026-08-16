import pytest

from clip_core import vocab_edit


def _data():
    return {"generic": ["clutch"], "games": {"war robots frontiers": {"groups": {"weapons": ["zeus"]}}}}


def test_add_generic_dedupes_case_insensitive():
    data = _data()
    added, skipped = vocab_edit.add_generic(data, ["Whiff", "clutch", "revenge"])
    assert added == ["Whiff", "revenge"]
    assert skipped == ["clutch"]
    assert data["generic"] == ["clutch", "Whiff", "revenge"]  # append order, casing preserved


def test_add_game_group_creates_and_sorts():
    data = _data()
    added, skipped = vocab_edit.add_game_group(data, "war robots frontiers", "weapons", ["Apollo", "zeus"])
    assert added == ["Apollo"]
    assert skipped == ["zeus"]
    assert data["games"]["war robots frontiers"]["groups"]["weapons"] == ["Apollo", "zeus"]  # sorted


def test_new_game_and_group_are_created():
    data = _data()
    vocab_edit.add_game_group(data, "apex", "abilities", ["wraith-phase"])
    assert data["games"]["apex"]["groups"]["abilities"] == ["wraith-phase"]


def test_comma_is_rejected():
    with pytest.raises(ValueError):
        vocab_edit.add_generic(_data(), ["bad,tag"])


def test_load_save_roundtrip(tmp_path):
    path = tmp_path / "tags.json"
    data = _data()
    vocab_edit.save_tags(data, path)
    assert vocab_edit.load_tags(path) == data
