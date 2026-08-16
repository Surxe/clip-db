#!/usr/bin/env python3
"""Extract the War Robots Frontiers ability -> torso-module implication map.

Every WRF torso grants exactly one signature ability (Garuda -> Snake Catcher,
Bulwark -> Absorber Sphere, ...). This encodes that torso<->ability pairing so a
classifier that assigns the *ability* tag can also assign its *module* tag: if a
clip is tagged "snake catcher" (or a nickname resolving to it), "garuda" follows.

The relationship is strictly one-to-one -- each torso ability belongs to a single
module and vice-versa. Generic leg/movement abilities shared across every chassis
(Jump Jet, Dash Thrusters, Pneumatic Vault, Glide Thrusters) are NOT torso
abilities and are deliberately excluded; the extractor asserts one-to-one and
fails loudly if a future game update breaks that.

The map is keyed by ability (the trigger) -> module (the tag to also assign),
because that is the direction the implication fires. It is trivially invertible.
Community nicknames for abilities (snaketrap / cage / trap ...) are not in the
game data and are handled separately as tag aliasing, not here.

Link chain in the source data:
    Ability.id  <--abilities_refs--  CharacterModule (id contains "_Torso")
    CharacterModule.id  <--character_module_mounts.character_module_ref--  Module (display name)

Usage:
    python scripts/extract_wrf_implications.py [OBJECTS_DIR] [--merge tag_implications.json]

OBJECTS_DIR defaults to the WRFrontiersDB-Data 'current/Objects' dir (env
WRF_OBJECTS_DIR or the sibling repo path). Without --merge it prints the game
block to stdout; with --merge it rewrites that file's games[GAME]["ability_to_module"].
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from pathlib import Path

GAME_NAME = "War Robots Frontiers"
MK_VARIANT = re.compile(r"\bMk\.?\s*(I|II|III|IV|V)\b", re.IGNORECASE)

DEFAULT_OBJECTS = os.environ.get(
    "WRF_OBJECTS_DIR",
    "/srv/dev/repos/WRFrontiersDB-Data/current/Objects",
)


def _name_en(entry: dict) -> str | None:
    name = entry.get("name")
    if isinstance(name, dict):
        return name.get("en") or name.get("Key")
    return name


def _ref_id(ref: str) -> str:
    """'OBJID_Ability::BP_Module_Garuda_Torso.1' -> 'BP_Module_Garuda_Torso.1'."""
    return (ref or "").split("::")[-1]


def extract(objects_dir: Path) -> dict:
    modules = json.loads((objects_dir / "Module.json").read_text())
    abilities = json.loads((objects_dir / "Ability.json").read_text())
    char_modules = json.loads((objects_dir / "CharacterModule.json").read_text())

    ability_name = {k: _name_en(v) for k, v in abilities.items()}

    # character-module id -> its Module.json display name(s) (Ready, non-Mk only,
    # matching the tag vocabulary produced by extract_wrf_tags.py).
    cm_to_module = defaultdict(set)
    for entry in modules.values():
        if entry.get("production_status") != "Ready":
            continue
        name = _name_en(entry)
        if not name or MK_VARIANT.search(name):
            continue
        for mount in entry.get("character_module_mounts") or []:
            cm_to_module[_ref_id(mount.get("character_module_ref"))].add(name)

    # Torso character modules only -> the signature ability they grant.
    ability_to_modules = defaultdict(set)
    module_to_abilities = defaultdict(set)
    for cm_id, cm in char_modules.items():
        if "_Torso" not in cm_id:
            continue
        for ref in cm.get("abilities_refs") or []:
            aname = ability_name.get(_ref_id(ref))
            if not aname:
                continue
            for mname in cm_to_module.get(cm_id, ()):
                ability_to_modules[aname].add(mname)
                module_to_abilities[mname].add(aname)

    # The rule must be one-to-one in both directions; refuse to emit otherwise.
    multi_mod = {a: sorted(m) for a, m in ability_to_modules.items() if len(m) > 1}
    multi_ab = {m: sorted(a) for m, a in module_to_abilities.items() if len(a) > 1}
    if multi_mod or multi_ab:
        raise ValueError(
            "torso ability<->module mapping is not one-to-one:\n"
            f"  ability -> multiple modules: {multi_mod}\n"
            f"  module -> multiple abilities: {multi_ab}"
        )

    mapping = {a: next(iter(m)) for a, m in ability_to_modules.items()}

    # comma is the index tag delimiter -- a tag must never contain one
    bad = [t for pair in mapping.items() for t in pair if "," in t]
    if bad:
        raise ValueError(f"tags contain a comma (illegal): {bad}")

    return {"ability_to_module": dict(sorted(mapping.items()))}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("objects_dir", nargs="?", default=DEFAULT_OBJECTS,
                    help=f"WRFrontiersDB-Data Objects dir (default: {DEFAULT_OBJECTS})")
    ap.add_argument("--merge", metavar="IMPLICATIONS_JSON",
                    help="Rewrite this file's War Robots Frontiers block in place.")
    args = ap.parse_args()

    block = extract(Path(args.objects_dir))
    count = len(block["ability_to_module"])

    if args.merge:
        path = Path(args.merge)
        data = json.loads(path.read_text()) if path.exists() else {}
        # Refresh only the generated ability_to_module map; preserve sibling keys
        # (e.g. the hand-maintained ability_implies effect map) in the game block.
        game = data.setdefault("games", {}).setdefault(GAME_NAME, {})
        game["ability_to_module"] = block["ability_to_module"]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"merged into {path}: {count} ability->module pairs")
    else:
        print(json.dumps({"games": {GAME_NAME: block}}, indent=2, ensure_ascii=False))
        print(f"# count: {count} ability->module pairs", flush=True)


if __name__ == "__main__":
    main()
