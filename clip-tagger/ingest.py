#!/usr/bin/env python3
"""Batch-ingest gaming clips: move masters out of staging, tag, and index them.

Reads masters from CLIP_INTAKE_DIR (the os-shared staging dir), pairs each with its
one-line description from the descriptions manifest (written by describe.py), classifies
them all in one batched call, moves each master (and its _merged.mp4, if present) into the
library, and writes an index row. Only masters are ingested (`*.mp4` excluding `*_merged.mp4`).

Masters with no manifest entry are skipped (run describe.py first), unless --allow-untagged.
Any classifier-proposed new tags are written to proposals.json next to the index for the
review step to resolve.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

import argparse

from clip_core import descriptions, index, media
from clip_core import tags as tagmod
from clip_core.classify import llm_classify_batch
from clip_core.config import load_config
from clip_core.relations import TagRelations
from clip_core.schema import connect

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _date_from_stem(stem: str) -> str | None:
    """Clips are named like 2026-07-30_22-03-03 -> pull the date out when present."""
    m = _DATE_RE.match(stem)
    return m.group(1) if m else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="preview without moving or writing")
    ap.add_argument("--embed", action="store_true", help="also embed tags in the master via exiftool")
    ap.add_argument("--allow-untagged", action="store_true", help="ingest masters that have no description (no tags)")
    args = ap.parse_args()

    cfg = load_config()
    vocab = tagmod.load_vocab(cfg.tags_path)
    relations = TagRelations.load(cfg.aliases_path, cfg.implications_path)
    conn = connect(cfg.index_path)
    manifest = descriptions.load(cfg.descriptions_path)

    masters = list(media.iter_masters(cfg.intake_dir))
    if not masters:
        print(f"No masters found in {cfg.intake_dir}")
        return

    described = [m for m in masters if media.stem_of(m) in manifest]
    undescribed = [m for m in masters if media.stem_of(m) not in manifest]
    if undescribed and not args.allow_untagged:
        print(f"Skipping {len(undescribed)} master(s) with no description (run describe.py, or use --allow-untagged):")
        for m in undescribed:
            print(f"  - {media.stem_of(m)}")
    ingest_masters = described + (undescribed if args.allow_untagged else [])
    if not ingest_masters:
        print("Nothing to ingest.")
        return

    # One batched classification for everything that has a description.
    items = [(media.stem_of(m), manifest[media.stem_of(m)]) for m in described]
    classified = llm_classify_batch(items, vocab, relations=relations, model=cfg.model) if items else {}

    proposals: dict[str, str] = {}
    for m in ingest_masters:
        stem = media.stem_of(m)
        duration = media.probe_duration(m)
        description = manifest.get(stem)
        result = classified.get(stem)
        tags = result.tags if result else []
        proposed = result.proposed_tag if result else None
        if proposed:
            proposals[stem] = proposed

        merged_src = m.with_name(media.merged_name_for(m))
        has_merged = merged_src.exists()

        if args.dry_run:
            extra = f" (+proposed: {proposed})" if proposed else ""
            merged_note = " +merged" if has_merged else ""
            print(f"[dry-run] {stem}: dur={duration}{merged_note} tags={tags}{extra}")
            continue

        master_dst = media.move_into_library(m, cfg.library_dir)
        merged_dst = media.move_into_library(merged_src, cfg.library_dir) if has_merged else None
        index.upsert_clip(
            conn,
            index.Clip(
                stem=stem,
                master_path=str(master_dst),
                merged_path=str(merged_dst) if merged_dst else None,
                date=_date_from_stem(stem),
                duration=duration,
                description=description,
                tags=tags,
            ),
        )
        if args.embed and tags:
            media.embed_tags(master_dst, tags)
        note = f" (proposed new tag: {proposed})" if proposed else ""
        print(f"ingested {stem} -> {master_dst} tags={tags}{note}")

    if not args.dry_run and proposals:
        proposals_path = Path(cfg.index_path).parent / "proposals.json"
        proposals_path.write_text(json.dumps(proposals, indent=2, ensure_ascii=False) + "\n")
        print(f"\n{len(proposals)} proposed tag(s) written to {proposals_path} -- resolve with review.py")


if __name__ == "__main__":
    main()
