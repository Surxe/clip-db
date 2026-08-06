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


def _structured(tmp_path):
    p = tmp_path / "tags.json"
    p.write_text(
        json.dumps(
            {
                "generic": ["clutch", "fail"],
                "games": {
                    "War Robots Frontiers": {
                        "groups": {
                            "weapons": ["Apollo", "Zeus"],
                            "modules": ["Aegis"],
                            "abilities": ["Ammo Fabricator"],
                        }
                    }
                },
            }
        )
    )
    return load_vocab(p)


def test_structured_flattens_generic_gamename_and_items(tmp_path):
    v = _structured(tmp_path)
    # generic + game name + every item are all valid tags (normalized)
    for t in ["clutch", "fail", "war robots frontiers", "apollo", "aegis", "ammo fabricator"]:
        assert t in v
    # group labels are NOT tags
    assert "weapons" not in v
    assert "modules" not in v
    assert "abilities" not in v


def test_structured_flat_order(tmp_path):
    v = _structured(tmp_path)
    assert v.as_list() == [
        "clutch", "fail",
        "war robots frontiers",
        "apollo", "zeus", "aegis", "ammo fabricator",
    ]


def test_markdown_shows_groups_but_not_as_tags(tmp_path):
    md = _structured(tmp_path).to_markdown()
    assert "## war robots frontiers" in md
    assert "**weapons**: apollo, zeus" in md
    assert "Generic tags" in md
