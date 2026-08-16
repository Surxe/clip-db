# clip-db

Tag, categorize, and query gaming clips. Controlled-vocabulary tagging where an LLM
maps a short free-text description onto a fixed tag list (`tags.json`) — no fuzzy
matching, no frame/audio AI. Batch tagging is a script; querying is a local MCP.

Two projects over one shared core:

```
clip_core/            # shared: config, tags vocab, sqlite index, media I/O, llm_classify, query
clip-tagger/          # ingest.py — batch: intake move + tag/categorize
clip-viewer-mcp/      # server.py — stdio MCP: query + retrieval
```

## Clip flow

1. Record on Windows or Linux. A separate (user-owned) step drops clips into the
   shared staging dir `os-shared/transfer/clips/` (`/mnt/os-shared/transfer/clips` on Linux).
2. `clip-tagger/ingest.py` moves each **master** out of staging into the ext4 library,
   probes metadata, classifies the description against the vocab, and writes an index row.
   Masters are `*.mp4` excluding `*_merged.mp4`; merged files are regenerable build output.
3. `clip-viewer-mcp/server.py` exposes query + retrieval tools to an MCP client (Claude Code).

## Tags

The vocabulary in `tags.json` has two tiers: **generic** tags (cross-game: `clutch`,
`fail`, …) and **game** tags, where the game's display name is a tag and each
weapon/module/ability is a tag, organised into readability groups whose labels are
*not* tags. The classifier is constrained to this list. See **[docs/tags.md](docs/tags.md)**
for the model, how the reader flattens/renders it, and how to add a new game.
War Robots Frontiers tags are regenerated from source via
`scripts/extract_wrf_tags.py`.

## Asset model

One logical asset per clip: a split-audio **master** (source of truth) plus an optional
regenerable `*_merged.mp4`, linked by filename stem (`clip123.mp4` ↔ `clip123_merged.mp4`
→ asset `clip123`). Tagged once, on the master. Tags live in a rebuildable SQLite index
(optionally embedded in the master via ExifTool).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements-dev.txt   # runtime + pytest
cp .env.example .env                            # then edit paths
.venv/bin/pytest
```

Paths are configured entirely via `.env` (see `.env.example`) so the repo stays generic.
Classification runs through the **`claude` CLI** (Claude Code in print mode), so it bills
against your logged-in Claude subscription — no Anthropic API key. The CLI must be on `PATH`
and authenticated (run `claude` once to log in). `CLIP_MODEL` (default `claude-sonnet-4-5`)
accepts any id/alias `claude --model` takes.

## Usage

Tagging is three decoupled steps: **describe** (write a sentence per clip), **ingest**
(batch-classify + move + index), **review** (fix tags / grow the vocab). Describing is
separate from tagging so the whole batch is classified in one call (the vocabulary is sent
once, not per clip).

```bash
.venv/bin/python clip-tagger/describe.py                  # sentence per staged master -> descriptions.json
.venv/bin/python clip-tagger/ingest.py --dry-run          # preview: one batched classify, no moves
.venv/bin/python clip-tagger/ingest.py                    # classify all, move into library, index
.venv/bin/python clip-tagger/review.py                    # confirm/fix tags; add proposed tags to the vocab
.venv/bin/python clip-viewer-mcp/server.py                # run the MCP over stdio
```

The per-clip descriptions live in a manifest (`descriptions.json` in the intake dir by
default; `CLIP_DESCRIPTIONS_PATH` to relocate) mapping asset stem -> sentence — hand-write it
for a backlog, or use `describe.py` interactively.
