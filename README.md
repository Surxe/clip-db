# clip-db

Tag, categorize, and query gaming clips. Controlled-vocabulary tagging where an LLM
maps a short free-text description onto a fixed tag list (`tags.json`) — no fuzzy
matching, no frame/audio AI. Batch tagging is a script; querying is a local MCP.

Two projects over one shared core:

```
clip_core/            # shared: config, tags vocab, sqlite index, media I/O, llm_classify, query
clip-tagger/          # ingest.py — batch: intake move + tag/categorize
clip-viewer-mcp/      # server.py — stdio MCP: query + retrieval
clip-distributor/     # compress.py + share.py — size-fit a clip under the Discord cap, to clipboard
```

## Clip flow

1. Record on Windows or Linux. A separate (user-owned) step drops clips into the
   shared staging dir `os-shared/transfer/clips/` (`/mnt/os-shared/transfer/clips` on Linux).
2. `clip-tagger/ingest.py` moves each **master** out of staging into the ext4 library,
   probes metadata, classifies the description provided the user as user-in-the-loop against the vocab, 
   writes an index row, and generates its mixed-audio `*_merged.mp4` 
   in the library (short masters only, gated by
   `CLIP_AUTO_MERGE_MAX_SECONDS`; `--no-merge` opts out). Masters are `*.mp4` excluding
   `*_merged.mp4`; merged files are regenerable build output (`merge.py` rebuilds them).
3. `clip-viewer-mcp/server.py` exposes query + retrieval tools to an MCP client (Claude Code).

## Tags

The vocabulary in `tags.json` has two tiers: **generic** tags (cross-game: `clutch`,
`fail`, …) and **game** tags, where the game's display name is a tag and each
weapon/module/ability is a tag, organised into readability groups whose labels are
*not* tags. The classifier is constrained to this list. See **[docs/tags.md](docs/tags.md)**
for the model, how the reader flattens/renders it, and how to add a new game.
War Robots Frontiers tags are regenerated from source via
`scripts/extract_wrf_tags.py`.

## Evaluation

The classifier is regression-tested against a hand-labeled golden set with a real
precision/recall harness — because the output is structured and constrained to the
vocabulary, quality is a measured number, not a vibe. Latest baseline
(`evals/baseline.json`, `claude-sonnet-4-5`, 15 cases × 5 runs each):

| Metric | Score |
|--|--|
| **Micro-F1** (tag-level) | **0.996** |
| Macro-F1 | 0.998 |
| Exact-match rate (whole clip correct) | 0.973 |
| Precision (all tags) | 1.000 — no wrong or invented tags |
| Proposed-tag false-positive rate | 0.000 |

What the harness (`evals/run_eval.py`) actually does:

- **Golden set** (`evals/golden.jsonl`) mixes literal cases, meaning-not-string cases
  (`"whiffed everything"` → `fail`, not a substring match), and alias/implication
  expansion (`"cage trap"` → `snake catcher` → its module `garuda`).
- **Regression gate** — `--gate` exits non-zero if micro-F1 falls below the stored
  baseline, so a prompt or model change can't silently degrade tagging.
- **Nondeterminism is measured, not ignored** — each case runs N times; the harness
  reports per-run F1 variance (mean 0.996, stdev 0.005) and a per-case stability rate.
- **Token-free reruns** — every model call is cached per run, so re-scoring iterates
  for free and only a deliberate re-collect spends model budget.

```bash
.venv/bin/python evals/run_eval.py --runs 5            # score against the golden set
.venv/bin/python evals/run_eval.py --runs 5 --gate     # regression gate vs baseline.json
```

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

Paths are configured entirely via `.env` (see `.env.example`).
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
