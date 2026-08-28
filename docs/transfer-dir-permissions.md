# Source vs. intake dir permissions

Clips are saved into the **source dir** (`CLIP_SOURCE_DIR`, e.g. the NTFS share
`/mnt/os-shared/transfer/clips`). The pipeline treats this dir as **read-only** and
never writes or deletes in it — so it needs no special group/write permissions, and it
can be mounted read-only to keep the `dev` account from touching Windows-owned files.

`clip-tagger/mirror.py` *copies* new masters out of the source into the writable
**intake dir** (`CLIP_INTAKE_DIR`, on ext4, e.g. `/srv/dev/clips/intake`). Everything
that mutates files — the descriptions manifest, `forced_tags.json`, and `ingest.py`'s
move into the library — happens in intake, which `dev` owns outright. `describe.py` and
`ingest.py` run the mirror automatically, so clips flow `source -> intake -> library`
with no manual copy step and no permission juggling.

## Why this replaces the old writable-share setup

Previously `CLIP_INTAKE_DIR` pointed straight at the NTFS share, so ingest had to
*move* (delete) files there, which required granting `dev` write access via the shared
`developers` group (`chgrp`/`chmod g+w`/setgid). A Windows-side rewrite kept resetting
that ownership back to `ethan`-only, so ingest would intermittently fail with a
`PermissionError`. Splitting a read-only source from a writable intake removes that
whole failure mode: the source can stay read-only forever.

## Dedupe

Because the source is never cleared, the mirror must avoid re-copying (and thus
re-ingesting) clips. A master is copied only when it is absent from both the intake dir
(copied, not yet ingested) and the library (already ingested) — no state file, just a
diff against what already exists. Deleting a clip from the library therefore makes it
eligible to be mirrored and re-ingested again from the source, which is the intended
behavior.
