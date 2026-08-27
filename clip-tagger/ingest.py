#!/usr/bin/env python3
"""Batch-ingest gaming clips: move masters out of staging, tag, and index them.

Reads masters from CLIP_INTAKE_DIR (the os-shared staging dir), pairs each with its
one-line description from the descriptions manifest (written by describe.py), classifies
them all in one batched call, moves each master (and its _merged.mp4, if present) into the
library, and writes an index row. Only masters are ingested (`*.mp4` excluding `*_merged.mp4`).

After a master lands in the library, its mixed-audio `_merged.mp4` is generated there and
attached to the index row -- so ingesting a clip also produces its merged rendition, gated
by CLIP_AUTO_MERGE_MAX_SECONDS (same threshold as `merge.py --auto`). A master that already
brought a `_merged.mp4` from staging is left as-is; pass --no-merge to skip merging entirely.

Masters with no manifest entry are skipped (run describe.py first), unless --allow-untagged.
Any classifier-proposed new tags are written to proposals.json next to the index for the
review step to resolve.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

import argparse

from clip_core import descriptions, forced_tags, index, media, merge
from clip_core import tags as tagmod
from clip_core.classify import llm_classify_batch
from clip_core.config import load_config
from clip_core.relations import TagRelations
from clip_core.schema import connect

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="preview without moving or writing")
    ap.add_argument("--embed", action="store_true", help="also embed tags in the master via exiftool")
    ap.add_argument("--allow-untagged", action="store_true", help="ingest masters that have no description (no tags)")
    ap.add_argument("--no-merge", action="store_true", help="skip generating a _merged.mp4 for each ingested master")
    args = ap.parse_args()

    cfg = load_config()
    vocab = tagmod.load_vocab(cfg.tags_path)
    relations = TagRelations.load(cfg.aliases_path, cfg.implications_path)
    conn = connect(cfg.index_path)
    manifest = descriptions.load(cfg.descriptions_path)

    # Forced tags: applied to every clip at ingest regardless of the classifier (e.g. the
    # game tag for a single-game batch). Fail fast if any isn't in the vocabulary.
    forced_map = forced_tags.load(cfg.forced_tags_path) if cfg.forced_tags_path else {}
    unknown_forced = sorted({t for lst in forced_map.values() for t in lst} - set(vocab.as_list()))
    if unknown_forced:
        print(f"error: forced tag(s) not in vocabulary (add to {cfg.tags_path}): {unknown_forced}")
        return
    if forced_map.get(forced_tags.ALL):
        print(f"Forcing {forced_map[forced_tags.ALL]} on every clip in this batch.\n")

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
        tags = list(result.tags) if result else []
        # Merge forced tags (batch-wide "*" plus per-stem), keeping classifier order.
        for t in forced_tags.for_stem(forced_map, stem):
            if t not in tags:
                tags.append(t)
        proposed = result.proposed_tag if result else None
        if proposed:
            proposals[stem] = proposed

        merged_src = m.with_name(media.merged_name_for(m))
        has_merged = merged_src.exists()
        # Generate a _merged.mp4 for short masters that didn't bring one from staging.
        will_merge = (
            not args.no_merge
            and not has_merged
            and duration is not None
            and duration <= cfg.auto_merge_max_seconds
        )

        if args.dry_run:
            extra = f" (+proposed: {proposed})" if proposed else ""
            merged_note = " +merged" if has_merged else (" +will-merge" if will_merge else "")
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
                date=media.resolve_date(master_dst, stem),
                duration=duration,
                description=description,
                tags=tags,
            ),
        )
        if args.embed and tags:
            media.embed_tags(master_dst, tags)
        note = f" (proposed new tag: {proposed})" if proposed else ""
        print(f"ingested {stem} -> {master_dst} tags={tags}{note}")
        if will_merge:
            result = merge.merge_master(conn, master_dst)
            print(f"  merged {stem} -> {result.merged_path}")

    if not args.dry_run and proposals:
        proposals_path = Path(cfg.index_path).parent / "proposals.json"
        proposals_path.write_text(json.dumps(proposals, indent=2, ensure_ascii=False) + "\n")
        print(f"\n{len(proposals)} proposed tag(s) written to {proposals_path} -- resolve with review.py")


if __name__ == "__main__":
    main()
