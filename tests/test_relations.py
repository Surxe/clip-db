import json

from clip_core.relations import TagRelations


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj))
    return p


def test_load_flattens_aliases_and_implications(tmp_path):
    aliases = _write(tmp_path, "aliases.json", {
        "games": {"WRF": {"aliases": {"Snake Catcher": ["snaketrap", "cage", "trap"]}}}
    })
    impl = _write(tmp_path, "impl.json", {
        "games": {"WRF": {"ability_to_module": {"Snake Catcher": "Garuda"}}}
    })
    rel = TagRelations.load(aliases, impl)
    assert rel.aliases["snaketrap"] == "snake catcher"  # normalized
    assert rel.aliases["cage"] == "snake catcher"
    assert rel.implications["snake catcher"] == ["garuda"]


def test_load_merges_module_and_effect_implications(tmp_path):
    impl = _write(tmp_path, "impl.json", {
        "games": {"WRF": {
            "ability_to_module": {"Optical Camo": "Pursuer"},
            "ability_implies": {"Optical Camo": ["stealth", "invis", "camo"]},
        }}
    })
    rel = TagRelations.load(None, impl)
    assert rel.implications["optical camo"] == ["pursuer", "stealth", "invis", "camo"]
    # ability expands to module + every effect, order-preserving, de-duped
    assert rel.resolve(["Optical Camo"]) == ["optical camo", "pursuer", "stealth", "invis", "camo"]


def test_missing_files_are_optional():
    rel = TagRelations.load(None, None)
    assert rel.resolve(["clutch"]) == ["clutch"]  # no-op passthrough


def test_resolve_normalizes_alias_then_expands_implication(tmp_path):
    aliases = _write(tmp_path, "aliases.json", {
        "games": {"WRF": {"aliases": {"Snake Catcher": ["snaketrap", "cage", "trap"]}}}
    })
    impl = _write(tmp_path, "impl.json", {
        "games": {"WRF": {"ability_to_module": {"Snake Catcher": "Garuda"}}}
    })
    rel = TagRelations.load(aliases, impl)
    # a nickname resolves to the canonical ability AND pulls in its module
    assert rel.resolve(["cage"]) == ["snake catcher", "garuda"]
    # the canonical ability directly still expands
    assert rel.resolve(["Snake Catcher"]) == ["snake catcher", "garuda"]


def test_resolve_dedupes_when_ability_and_module_both_present(tmp_path):
    impl = _write(tmp_path, "impl.json", {
        "games": {"WRF": {"ability_to_module": {"Snake Catcher": "Garuda"}}}
    })
    rel = TagRelations.load(None, impl)
    assert rel.resolve(["snake catcher", "garuda"]) == ["snake catcher", "garuda"]
    # module alone is not expanded back to the ability (one-directional)
    assert rel.resolve(["garuda"]) == ["garuda"]


def test_resolve_preserves_unrelated_tags_and_order(tmp_path):
    impl = _write(tmp_path, "impl.json", {
        "games": {"WRF": {"ability_to_module": {"Snake Catcher": "Garuda"}}}
    })
    rel = TagRelations.load(None, impl)
    assert rel.resolve(["clutch", "snake catcher", "ace"]) == [
        "clutch", "snake catcher", "garuda", "ace"
    ]


def test_hint_markdown_lists_nicknames(tmp_path):
    aliases = _write(tmp_path, "aliases.json", {
        "games": {"WRF": {"aliases": {"Snake Catcher": ["snaketrap", "cage", "trap"]}}}
    })
    rel = TagRelations.load(aliases, None)
    md = rel.hint_markdown()
    assert "snake catcher: snaketrap, cage, trap" in md
    # no aliases -> no hint block
    assert TagRelations.load(None, None).hint_markdown() == ""
