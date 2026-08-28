#!/usr/bin/env python3
"""Delete a clip from the library and index.

Removes an asset's index row plus its library files -- the master and the
regenerable _merged.mp4. Accepts either the asset stem or a path to any of its
files (the _merged suffix is stripped, so pointing at the merged file works too).

  # by stem
  python scripts/delete_clip.py "steal powerup from nemesis with nuke"

  # by path (master or _merged), several at once
  python scripts/delete_clip.py "/srv/dev/clips/library/the goblin combo.mp4"

  --keep-files   drop only the index row; leave the library files in place
  --dry-run      print what would happen, change nothing
  -y, --yes      skip the confirmation prompt

The source staging file (in the intake dir) is never touched.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

from clip_core import index, media, schema
from clip_core.config import load_config


def _library_files(clip, library_dir: Path) -> list[Path]:
    """Files to remove for an asset: its recorded master/merged paths, plus the
    canonical library master/merged names as a fallback (dedup, existing only)."""
    candidates = [clip.master_path, clip.merged_path]
    master_name = f"{clip.stem}.mp4"
    candidates += [
        str(library_dir / master_name),
        str(library_dir / media.merged_name_for(library_dir / master_name)),
    ]
    seen: dict[str, Path] = {}
    for c in candidates:
        if not c:
            continue
        p = Path(c)
        if p.exists() and str(p) not in seen:
            seen[str(p)] = p
    return list(seen.values())


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("targets", nargs="+", metavar="STEM_OR_PATH",
                    help="Asset stem, or path to one of its files.")
    ap.add_argument("--keep-files", action="store_true",
                    help="Delete only the index row; leave library files in place.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would happen without changing anything.")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="Skip the confirmation prompt.")
    args = ap.parse_args()

    cfg = load_config()
    conn = schema.connect(cfg.index_path)

    stems = [media.stem_of(t) for t in args.targets]
    plan = []  # (stem, clip_or_None, files)
    for stem in dict.fromkeys(stems):  # dedupe, preserve order
        clip = index.get_clip(conn, stem)
        files = [] if (clip is None or args.keep_files) else _library_files(clip, cfg.library_dir)
        plan.append((stem, clip, files))

    for stem, clip, files in plan:
        if clip is None:
            print(f"not indexed (skip): {stem!r}")
            continue
        print(f"clip: {stem!r}")
        if args.keep_files:
            print("  index row only (--keep-files)")
        elif files:
            for f in files:
                print(f"  file: {f}")
        else:
            print("  no library files found")

    to_delete = [p for p in plan if p[1] is not None]
    if not to_delete:
        print("nothing to delete.")
        return
    if args.dry_run:
        print("dry run -- no changes made.")
        return
    if not args.yes:
        ans = input(f"Delete {len(to_delete)} clip(s)? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("aborted.")
            return

    for stem, clip, files in to_delete:
        index.delete_clip(conn, stem)
        try:  # best-effort: drop the clip's semantic vector too, if the index exists
            from clip_core import embed
            embed.load_vec(conn)
            embed.remove_clip(conn, stem)
        except Exception:  # noqa: BLE001 -- no vector index / deps is fine, keep deleting
            pass
        for f in files:
            try:
                f.unlink()
                print(f"removed: {f}")
            except OSError as e:
                print(f"WARN could not remove {f}: {e}", file=sys.stderr)
        print(f"deleted from index: {stem!r}")


if __name__ == "__main__":
    main()
