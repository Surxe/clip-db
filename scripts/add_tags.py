#!/usr/bin/env python3
"""Add tags to tags.json in bulk. Idempotent, case-insensitive dedupe, comma-guarded.

  # generic (cross-game) tags
  python scripts/add_tags.py --generic whiff "no scope" revenge

  # game/group tags (game and group are created if missing; group lists stay sorted)
  python scripts/add_tags.py --game "War Robots Frontiers" --group weapons Apollo Zeus

Prints what was added vs. skipped (already present). Preserves display casing.

Thin CLI over clip_core.vocab_edit -- the same insertion logic the interactive review
step uses, so there is one source of truth.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

from clip_core import vocab_edit


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--generic", nargs="+", metavar="TAG", help="Add cross-game generic tags.")
    ap.add_argument("--game", metavar="NAME", help="Game display name (created if missing).")
    ap.add_argument("--group", metavar="LABEL", help="Group under --game (created if missing).")
    ap.add_argument("tags", nargs="*", metavar="TAG", help="Item tags for --game/--group.")
    args = ap.parse_args()

    if not (args.generic or args.game):
        ap.error("nothing to add: pass --generic or --game/--group")

    data = vocab_edit.load_tags()
    try:
        if args.generic:
            added, skipped = vocab_edit.add_generic(data, args.generic)
            print(f"generic: +{len(added)} {added}  (skipped {len(skipped)})")

        if args.game or args.group or args.tags:
            if not (args.game and args.group and args.tags):
                ap.error("game tags need --game NAME --group LABEL TAG [TAG ...]")
            added, skipped = vocab_edit.add_game_group(data, args.game, args.group, args.tags)
            print(f"{args.game} / {args.group}: +{len(added)} {added}  (skipped {len(skipped)})")
    except ValueError as e:
        sys.exit(f"error: {e}")

    vocab_edit.save_tags(data)


if __name__ == "__main__":
    main()
