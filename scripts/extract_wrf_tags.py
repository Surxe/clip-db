#!/usr/bin/env python3
"""Extract the War Robots Frontiers game block for tags.json from WRFrontiersDB-Data.

This encodes the WRF extraction logic documented in docs/tags.md so the game's tag
lists can be regenerated when the game updates, rather than hand-maintained.

  weapons:       Ready modules whose module_type_ref contains "Weapon"
  modules:       Ready modules of type chassis/torso/shoulder/Titan (robot parts). Ability-slot
                 gadget modules are excluded -- their name equals the ability they grant, which
                 is already listed under abilities (avoids the modules/abilities duplicate).
  abilities:     all abilities (no production_status filter) -- includes each torso's ability
                 and every ability-slot gadget (Umbrella, Repulsor, ...)
  pilot talents: all pilot talents (no production_status filter)
  excluded:      "Mk. I" / "Mk. II" variant names
  names:         each entry's name.en; groups are distinct + sorted

Usage:
    python scripts/extract_wrf_tags.py [OBJECTS_DIR] [--merge tags.json]

OBJECTS_DIR defaults to the WRFrontiersDB-Data 'current/Objects' dir (env
WRF_OBJECTS_DIR or the sibling repo path). Without --merge it prints the game block
to stdout; with --merge it rewrites that file's games["War Robots Frontiers"] in place.
"""
from __future__ import annotations

import argparse
import json
import os
import re
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


def _distinct_sorted(names) -> list[str]:
    return sorted(dict.fromkeys(n for n in names if n))


def extract(objects_dir: Path) -> dict:
    modules = json.loads((objects_dir / "Module.json").read_text())
    abilities = json.loads((objects_dir / "Ability.json").read_text())
    talents = json.loads((objects_dir / "PilotTalent.json").read_text())

    weapons, other_modules = [], []
    for entry in modules.values():
        if entry.get("production_status") != "Ready":
            continue
        name = _name_en(entry)
        if not name or MK_VARIANT.search(name):
            continue
        module_type = entry.get("module_type_ref") or ""
        if "Weapon" in module_type:
            weapons.append(name)
        elif "Ability" in module_type:
            # Ability-slot gadget: its module name is identical to the ability it
            # grants, which is already emitted from Ability.json into the abilities
            # group. Listing it here too would duplicate it, so modules stays the
            # robot chassis/torso/shoulder/Titan parts only.
            continue
        else:
            other_modules.append(name)

    ability_names = [_name_en(e) for e in abilities.values()]
    talent_names = [_name_en(e) for e in talents.values()]

    groups = {
        "weapons": _distinct_sorted(weapons),
        "modules": _distinct_sorted(other_modules),
        "abilities": _distinct_sorted(ability_names),
        "pilot talents": _distinct_sorted(talent_names),
    }

    # comma is the index tag delimiter — a tag must never contain one
    bad = [t for items in groups.values() for t in items if "," in t]
    if bad:
        raise ValueError(f"tags contain a comma (illegal): {bad}")

    return {"groups": groups}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("objects_dir", nargs="?", default=DEFAULT_OBJECTS,
                    help=f"WRFrontiersDB-Data Objects dir (default: {DEFAULT_OBJECTS})")
    ap.add_argument("--merge", metavar="TAGS_JSON",
                    help="Rewrite this tags.json's War Robots Frontiers block in place.")
    args = ap.parse_args()

    block = extract(Path(args.objects_dir))
    counts = {k: len(v) for k, v in block["groups"].items()}

    if args.merge:
        path = Path(args.merge)
        data = json.loads(path.read_text())
        # Refresh only the generated groups; preserve any hand-maintained groups
        # (e.g. effect tags) added to the game block so they survive a re-extract.
        game = data.setdefault("games", {}).setdefault(GAME_NAME, {})
        game.setdefault("groups", {}).update(block["groups"])
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"merged into {path}: {counts}")
    else:
        print(json.dumps({GAME_NAME: block}, indent=2, ensure_ascii=False))
        print(f"# counts: {counts}", flush=True)


if __name__ == "__main__":
    main()
