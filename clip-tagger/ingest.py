#!/usr/bin/env python3
"""Batch-ingest gaming clips: move masters out of staging, tag, and index them.

Reads masters from CLIP_INTAKE_DIR (the os-shared staging dir), moves each into the
library, probes metadata, classifies the description against the vocab, and writes an
index row. Only masters are ingested (`*.mp4` excluding `*_merged.mp4`).

NOTE: the per-clip description source is a stub — currently a single --description applied
to all masters found. A real sidecar/manifest/interactive input is a follow-up.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

import argparse

from clip_core import index, media
from clip_core import tags as tagmod
from clip_core.classify import llm_classify
from clip_core.config import load_config
from clip_core.schema import connect


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--description", default="", help="one-line description (stub input)")
    ap.add_argument("--dry-run", action="store_true", help="preview without moving or writing")
    ap.add_argument("--embed", action="store_true", help="also embed tags in the master via exiftool")
    args = ap.parse_args()

    cfg = load_config()
    vocab = tagmod.load_vocab(cfg.tags_path)
    conn = connect(cfg.index_path)

    masters = list(media.iter_masters(cfg.intake_dir))
    if not masters:
        print(f"No masters found in {cfg.intake_dir}")
        return

    for m in masters:
        stem = media.stem_of(m)
        duration = media.probe_duration(m)

        tags: list[str] = []
        proposed = None
        if args.description:
            result = llm_classify(args.description, vocab, model=cfg.model)
            tags, proposed = result.tags, result.proposed_tag

        if args.dry_run:
            extra = f" (+proposed: {proposed})" if proposed else ""
            print(f"[dry-run] {stem}: dur={duration} tags={tags}{extra}")
            continue

        dst = media.move_into_library(m, cfg.library_dir)
        index.upsert_clip(
            conn,
            index.Clip(stem=stem, master_path=str(dst), duration=duration, tags=tags),
        )
        if args.embed and tags:
            media.embed_tags(dst, tags)
        note = f" (proposed new tag: {proposed})" if proposed else ""
        print(f"ingested {stem} -> {dst} tags={tags}{note}")


if __name__ == "__main__":
    main()
