#!/usr/bin/env python3
"""Interactively review tagged clips: confirm tags, fix them, and grow the vocabulary.

By default it walks clips the classifier was unsure about -- those with a proposed new tag
(from proposals.json) or no tags at all. `--all` walks every clip. For each you can edit the
tag list; any tag you type that isn't in the vocabulary yet is offered for addition to
tags.json (generic, or a game's weapons/modules/abilities) via the shared vocab_edit helper,
then attached to the clip.

  review.py            # clips with proposed tags or no tags
  review.py --all      # every clip
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

import argparse

from clip_core import index, tags as tagmod, vocab_edit
from clip_core.config import load_config
from clip_core.schema import connect


def _resolve_new_tag(cfg, tag: str) -> bool:
    """Offer to add an unknown tag to the vocabulary. Returns True if it was added."""
    data = vocab_edit.load_tags(cfg.tags_path)
    games = sorted(data["games"])
    print(f"    '{tag}' is not in the vocabulary. Add it as:")
    print("      [g] generic (cross-game)")
    for i, g in enumerate(games, 1):
        print(f"      [{i}] {g} (choose a group next)")
    print("      [k] keep on this clip without adding to the vocabulary")
    choice = input("    > ").strip().lower()
    try:
        if choice == "g":
            vocab_edit.add_generic(data, [tag])
        elif choice.isdigit() and 1 <= int(choice) <= len(games):
            game = games[int(choice) - 1]
            group = input("    group (weapons/modules/abilities/...): ").strip() or "misc"
            vocab_edit.add_game_group(data, game, group, [tag])
        else:
            return False
    except ValueError as e:
        print(f"    skipped: {e}")
        return False
    vocab_edit.save_tags(data, cfg.tags_path)
    print(f"    added '{tag}' to the vocabulary.")
    return True


def _edit_tags(cfg, conn, clip) -> None:
    raw = input(f"    tags [{', '.join(clip.tags)}]> ").strip()
    if not raw:
        return
    vocab = tagmod.load_vocab(cfg.tags_path)
    new_tags = [t.strip() for t in raw.split(",") if t.strip()]
    for t in new_tags:
        if t not in vocab:
            _resolve_new_tag(cfg, t)  # add to vocab if the user wants; tag is kept either way
    index.set_tags(conn, clip.stem, new_tags)
    print(f"    tags set: {index.get_clip(conn, clip.stem).tags}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="review every clip, not just uncertain ones")
    args = ap.parse_args()

    cfg = load_config()
    conn = connect(cfg.index_path)

    proposals_path = Path(cfg.index_path).parent / "proposals.json"
    proposals = json.loads(proposals_path.read_text()) if proposals_path.exists() else {}

    if args.all:
        clips = index.all_clips(conn)
    else:
        untagged = {c.stem for c in index.list_untagged(conn)}
        wanted = set(proposals) | untagged
        clips = [c for c in index.all_clips(conn) if c.stem in wanted]

    if not clips:
        print("Nothing to review.")
        return

    print(f"Reviewing {len(clips)} clip(s). Per clip: [e]dit tags, [p] add proposed tag, Enter=next, [q]uit.\n")
    for i, clip in enumerate(clips, 1):
        proposed = proposals.get(clip.stem)
        print(f"[{i}/{len(clips)}] {clip.stem}")
        print(f"    description: {clip.description or '(none)'}")
        print(f"    tags: {clip.tags or '(none)'}")
        if proposed:
            print(f"    proposed new tag: {proposed}")
        action = input("    action> ").strip().lower()
        if action == "q":
            break
        if action == "e":
            _edit_tags(cfg, conn, clip)
        elif action == "p" and proposed:
            if _resolve_new_tag(cfg, proposed):
                index.add_tag(conn, clip.stem, proposed)
                print(f"    tags now: {index.get_clip(conn, clip.stem).tags}")
        # resolved either way: drop any proposal for this clip
        proposals.pop(clip.stem, None)

    if proposals:
        proposals_path.write_text(json.dumps(proposals, indent=2, ensure_ascii=False) + "\n")
    elif proposals_path.exists():
        proposals_path.unlink()
    print("\nReview complete.")


if __name__ == "__main__":
    main()
