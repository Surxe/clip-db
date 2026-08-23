#!/usr/bin/env python3
"""Interactively describe clips: one sentence per master, saved to the descriptions manifest.

Walks masters staged in CLIP_INTAKE_DIR, opens each in the default player, and prompts for
a one-line description. No AI here -- describing is decoupled from tagging (that happens in
ingest). Progress is saved after every clip, so the run is safe to stop and resume.

  describe.py                 # describe masters that have no description yet
  describe.py --all           # revisit every master, pre-filling the current sentence
  describe.py --no-open       # don't launch the player (headless / scripted)
  describe.py --force-tag "War Robots Frontiers"   # pin a tag on the whole batch (see below)

--force-tag records a tag applied to *every* master in this intake at ingest, without
writing it into any description and without relying on the classifier -- ideal for a
single-game batch where you want the game tag guaranteed. Repeatable; the tag must exist
in the vocabulary (tags.json). It is stored batch-wide in forced_tags.json alongside the
descriptions manifest and merged into each clip's tags by ingest.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

import argparse

from clip_core import descriptions, forced_tags, media
from clip_core import tags as tagmod
from clip_core.config import load_config


def _open_in_player(master: Path) -> None:
    """Open the clip in the default handler (avidemux for mp4). Prefer the watchable
    merged rendition if it is staged alongside the master; best-effort."""
    merged = master.with_name(media.merged_name_for(master))
    target = merged if merged.exists() else master
    try:
        subprocess.Popen(
            ["xdg-open", str(target)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:  # noqa: BLE001 - player is a convenience, never fatal
        print(f"  (could not open player: {e})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="revisit every master, not just undescribed ones")
    ap.add_argument("--no-open", action="store_true", help="do not launch the player")
    ap.add_argument(
        "--force-tag", action="append", default=[], metavar="TAG",
        help="tag forced onto every clip in this intake at ingest (repeatable); recorded "
             "batch-wide, no need to write it into any description. Must exist in the vocab.",
    )
    args = ap.parse_args()

    cfg = load_config()

    if args.force_tag:
        vocab = tagmod.load_vocab(cfg.tags_path)
        normed = [tagmod.normalize(t) for t in args.force_tag]
        unknown = [t for t in normed if t not in vocab]
        if unknown:
            print(f"error: forced tag(s) not in vocabulary (add to {cfg.tags_path} first): {unknown}")
            sys.exit(1)
        fmap = forced_tags.load(cfg.forced_tags_path)
        fmap[forced_tags.ALL] = list(dict.fromkeys(fmap.get(forced_tags.ALL, []) + normed))
        forced_tags.save(cfg.forced_tags_path, fmap)
        print(f"Forcing {fmap[forced_tags.ALL]} on every clip in this intake at ingest "
              f"(saved to {cfg.forced_tags_path}).\n")

    manifest = descriptions.load(cfg.descriptions_path)
    masters = list(media.iter_masters(cfg.intake_dir))
    if not masters:
        print(f"No masters found in {cfg.intake_dir}")
        return

    todo = [m for m in masters if args.all or media.stem_of(m) not in manifest]
    if not todo:
        print(f"All {len(masters)} masters already described. Use --all to revisit.")
        return

    print(f"Describing {len(todo)} of {len(masters)} masters. Blank line keeps the current value; Ctrl-C to stop.\n")
    for i, master in enumerate(todo, 1):
        stem = media.stem_of(master)
        duration = media.probe_duration(master)
        current = manifest.get(stem, "")
        print(f"[{i}/{len(todo)}] {stem}  (dur={duration})")
        if current:
            print(f"  current: {current}")
        if not args.no_open:
            _open_in_player(master)
        try:
            sentence = input("  describe> ").strip()
        except EOFError:
            print("\n(end of input)")
            break
        if not sentence:
            print("  (kept)" if current else "  (skipped)")
            continue
        manifest[stem] = sentence
        descriptions.save(cfg.descriptions_path, manifest)

    print(f"\nSaved {len(manifest)} descriptions to {cfg.descriptions_path}")


if __name__ == "__main__":
    main()
