#!/usr/bin/env python3
"""Mirror new masters from the read-only source dir (CLIP_SOURCE_DIR) into CLIP_INTAKE_DIR.

The source is where clips are saved (e.g. the NTFS share, mounted read-only). The pipeline
never writes there, so this copies -- rather than moves -- each new master into the writable
intake dir, where describe.py/ingest.py take over. Already-ingested masters (present in the
library) and ones already staged in intake are skipped, so re-runs bring only new saves.

This runs automatically at the start of describe.py and ingest.py, so you normally never
call it by hand; it stays runnable for a manual mirror or a dry-run preview.

  mirror.py             # mirror new masters into intake
  mirror.py --dry-run   # list what would be copied, copy nothing
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

import argparse

from clip_core.config import load_config
from clip_core.intake_sync import sync_intake


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="preview what would be copied, copy nothing")
    args = ap.parse_args()

    cfg = load_config()
    if cfg.source_dir is None:
        print("CLIP_SOURCE_DIR is not set -- nothing to mirror (intake is authoritative).")
        return
    copied = sync_intake(cfg, dry_run=args.dry_run)
    if not copied:
        print(f"Intake is up to date with {cfg.source_dir} (nothing new to copy).")


if __name__ == "__main__":
    main()
