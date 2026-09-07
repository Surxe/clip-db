#!/usr/bin/env python3
"""Add tags to tags.json in bulk. Idempotent, case-insensitive dedupe, comma-guarded.

  # generic (cross-game) tags
  python scripts/add_tags.py --generic whiff "no scope" revenge

  # game/group tags (game and group are created if missing; group lists stay sorted)
  python scripts/add_tags.py --game "War Robots Frontiers" --group weapons Apollo Zeus

  # an implication: a tag expands to imply others at tag time (players imply notable-player)
  python scripts/add_tags.py --game "War Robots Frontiers" --implies "sir tubins" notable-player

  # an alias: community nicknames that resolve to one canonical vocab tag
  python scripts/add_tags.py --game "War Robots Frontiers" --alias Incinerator incin

Prints what was added vs. skipped (already present). Preserves display casing. --group edits
tags.json; --implies edits tag_implications.json; --alias edits tag_aliases.json.

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
    ap.add_argument("--implies", nargs="+", metavar="TAG",
                    help="SOURCE TARGET [TARGET ...]: SOURCE implies the TARGETs (needs --game).")
    ap.add_argument("--alias", nargs="+", metavar="TAG",
                    help="CANONICAL NICK [NICK ...]: NICKs alias to CANONICAL (needs --game).")
    ap.add_argument("tags", nargs="*", metavar="TAG", help="Item tags for --game/--group.")
    args = ap.parse_args()

    if not (args.generic or args.group or args.tags or args.implies or args.alias):
        ap.error("nothing to add: pass --generic, --game/--group, --implies, or --alias")

    try:
        if args.generic:
            data = vocab_edit.load_tags()
            added, skipped = vocab_edit.add_generic(data, args.generic)
            vocab_edit.save_tags(data)
            print(f"generic: +{len(added)} {added}  (skipped {len(skipped)})")

        if args.group or args.tags:
            if not (args.game and args.group and args.tags):
                ap.error("game tags need --game NAME --group LABEL TAG [TAG ...]")
            data = vocab_edit.load_tags()
            added, skipped = vocab_edit.add_game_group(data, args.game, args.group, args.tags)
            vocab_edit.save_tags(data)
            print(f"{args.game} / {args.group}: +{len(added)} {added}  (skipped {len(skipped)})")

        if args.implies:
            if not args.game or len(args.implies) < 2:
                ap.error("--implies needs --game NAME and SOURCE TARGET [TARGET ...]")
            source, targets = args.implies[0], args.implies[1:]
            data = vocab_edit.load_relations(vocab_edit.IMPLICATIONS_JSON)
            added, skipped = vocab_edit.add_implication(data, args.game, source, targets)
            vocab_edit.save_relations(data, vocab_edit.IMPLICATIONS_JSON)
            print(f"{args.game} / implies {source!r}: +{len(added)} {added}  (skipped {len(skipped)})")

        if args.alias:
            if not args.game or len(args.alias) < 2:
                ap.error("--alias needs --game NAME and CANONICAL NICK [NICK ...]")
            canonical, nicks = args.alias[0], args.alias[1:]
            data = vocab_edit.load_relations(vocab_edit.ALIASES_JSON)
            added, skipped = vocab_edit.add_alias(data, args.game, canonical, nicks)
            vocab_edit.save_relations(data, vocab_edit.ALIASES_JSON)
            print(f"{args.game} / alias {canonical!r}: +{len(added)} {added}  (skipped {len(skipped)})")
    except ValueError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
