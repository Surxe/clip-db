#!/usr/bin/env python3
"""Embed indexed clips into the sqlite-vec vector index for semantic search.

Walks the clip index and embeds each clip's `description + tags` into `vec_clips`
(the vector table beside the main index). Incremental by default -- only clips without
a vector are embedded -- so this is safe to re-run and to call after new ingests.

  python scripts/embed_backfill.py --dry-run   # preview, write nothing
  python scripts/embed_backfill.py             # embed only clips missing a vector
  python scripts/embed_backfill.py --all       # re-embed EVERY clip (after a model change)

The embedding model (CLIP_EMBED_MODEL) is pinned: vectors are only comparable when made
by the same model. If the model recorded in the index differs from the configured one,
this refuses a partial run and tells you to re-embed with --all (which restamps the model).

A clip with neither a description nor tags has nothing to embed and is skipped.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

from clip_core import embed, index
from clip_core.config import load_config
from clip_core.schema import connect


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="preview without writing")
    ap.add_argument("--all", action="store_true", help="re-embed every clip, not just those missing a vector")
    args = ap.parse_args()

    cfg = load_config()
    conn = connect(cfg.index_path)
    embed.ensure_vec_table(conn)

    stored = embed.stored_model(conn)
    if stored and stored != cfg.embed_model and not args.all:
        print(
            f"model mismatch: index was embedded with {stored!r} but config is {cfg.embed_model!r}.\n"
            f"Vectors from different models are not comparable -- re-embed everything with --all.",
            file=sys.stderr,
        )
        return 1

    embedded = skipped_have = skipped_empty = 0
    for clip in index.all_clips(conn):
        if not args.all and embed.has_vector(conn, clip.stem):
            skipped_have += 1
            continue
        if not embed.embedding_text(clip):
            skipped_empty += 1
            continue
        action = "would embed" if args.dry_run else "embedded"
        print(f"  {action} {clip.stem}")
        if not args.dry_run:
            embed.index_clip(conn, clip)
        embedded += 1

    if args.all and not args.dry_run:
        embed.set_stored_model(conn)  # restamp the model we just embedded with

    verb = "would embed" if args.dry_run else "embedded"
    print(f"\n{verb} {embedded}; already had vector {skipped_have}; nothing to embed {skipped_empty}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
