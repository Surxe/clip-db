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


def test_add_implication_creates_and_dedupes():
    data = {"games": {}}
    added, skipped = vocab_edit.add_implication(data, "war robots frontiers", "sir tubins", ["notable-player"])
    assert added == ["notable-player"] and skipped == []
    added, skipped = vocab_edit.add_implication(data, "war robots frontiers", "sir tubins", ["Notable-Player", "reveal"])
    assert added == ["reveal"] and skipped == ["Notable-Player"]  # case-insensitive dedupe, append order
    block = data["games"]["war robots frontiers"][vocab_edit.IMPLIES_KEY]
    assert block["sir tubins"] == ["notable-player", "reveal"]


def test_add_implication_promotes_string_value():
    data = {"games": {"g": {vocab_edit.IMPLIES_KEY: {"src": "one"}}}}
    added, _ = vocab_edit.add_implication(data, "g", "src", ["two"])
    assert added == ["two"]
    assert data["games"]["g"][vocab_edit.IMPLIES_KEY]["src"] == ["one", "two"]


def test_add_alias_creates_and_dedupes():
    data = {"games": {}}
    added, skipped = vocab_edit.add_alias(data, "war robots frontiers", "Incinerator", ["incin", "Incin"])
    assert added == ["incin"] and skipped == ["Incin"]
    assert data["games"]["war robots frontiers"]["aliases"]["Incinerator"] == ["incin"]


def test_implication_and_alias_reject_commas():
    with pytest.raises(ValueError):
        vocab_edit.add_implication({"games": {}}, "g", "bad,src", ["x"])
    with pytest.raises(ValueError):
        vocab_edit.add_alias({"games": {}}, "g", "canon", ["bad,nick"])


def test_relations_load_save_roundtrip(tmp_path):
    path = tmp_path / "rel.json"
    assert vocab_edit.load_relations(path) == {"games": {}}  # missing file -> empty
    data = {"games": {"g": {vocab_edit.IMPLIES_KEY: {"a": ["b"]}}}}
    vocab_edit.save_relations(data, path)
    assert vocab_edit.load_relations(path) == data
