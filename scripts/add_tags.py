#!/usr/bin/env python3
"""Add tags to tags.json in bulk. Idempotent, case-insensitive dedupe, comma-guarded.

  # generic (cross-game) tags
  python scripts/add_tags.py --generic whiff "no scope" revenge

  # game/group tags (game and group are created if missing; group lists stay sorted)
  python scripts/add_tags.py --game "War Robots Frontiers" --group weapons Apollo Zeus

Prints what was added vs. skipped (already present). Preserves display casing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TAGS_JSON = Path(__file__).resolve().parent.parent / "tags.json"


def _add(existing: list[str], new: list[str], *, sort: bool) -> tuple[list[str], list[str], list[str]]:
    have = {t.lower() for t in existing}
    added, skipped = [], []
    for t in new:
        t = t.strip()
        if not t:
            continue
        if "," in t:
            sys.exit(f"error: tag {t!r} contains a comma (illegal — comma is the index delimiter)")
        (skipped if t.lower() in have else added).append(t)
        have.add(t.lower())
    result = existing + added
    if sort:
        result = sorted(dict.fromkeys(result), key=str.lower)
    return result, added, skipped


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--generic", nargs="+", metavar="TAG", help="Add cross-game generic tags.")
    ap.add_argument("--game", metavar="NAME", help="Game display name (created if missing).")
    ap.add_argument("--group", metavar="LABEL", help="Group under --game (created if missing).")
    ap.add_argument("tags", nargs="*", metavar="TAG", help="Item tags for --game/--group.")
    args = ap.parse_args()

    data = json.loads(TAGS_JSON.read_text())
    data.setdefault("generic", [])
    data.setdefault("games", {})

    if args.generic:
        data["generic"], added, skipped = _add(data["generic"], args.generic, sort=False)
        print(f"generic: +{len(added)} {added}  (skipped {len(skipped)})")

    if args.game or args.group or args.tags:
        if not (args.game and args.group and args.tags):
            ap.error("game tags need --game NAME --group LABEL TAG [TAG ...]")
        groups = data["games"].setdefault(args.game, {}).setdefault("groups", {})
        groups[args.group], added, skipped = _add(groups.get(args.group, []), args.tags, sort=True)
        print(f'{args.game} / {args.group}: +{len(added)} {added}  (skipped {len(skipped)})')

    if not (args.generic or args.game):
        ap.error("nothing to add: pass --generic or --game/--group")

    TAGS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
