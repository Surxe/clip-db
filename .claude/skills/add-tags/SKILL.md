---
name: add-tags
description: Add tags to this repo's tags.json in bulk — generic (cross-game) tags, or a game's weapon/module/ability tags. Use when Ethan is describing clips and comes up with new tags to add on the fly.
---

# Add tags

Vocabulary model: `generic` tags (cross-game) + `games` → groups → item tags. The
game name is a tag, each item is a tag; **group labels are not tags**. Full model:
`docs/tags.md`. Everything is lowercased on load, so casing here is cosmetic.

Use the helper — it dedupes (case-insensitive), rejects commas, and keeps game
groups sorted. Don't hand-edit `tags.json`.

```bash
# generic (cross-game)
.venv/bin/python scripts/add_tags.py --generic whiff "no scope" revenge

# game / group items (game + group auto-created if new)
.venv/bin/python scripts/add_tags.py --game "War Robots Frontiers" --group weapons Apollo Zeus
```

## Bulk / on-the-fly

- Collect the new tags Ethan mentions, then make **one call per bucket**: one
  `--generic` call, one call per `--game`+`--group`. Pass many tags at once.
- Decide the bucket by meaning: cross-game feeling/outcome → `--generic`; a named
  weapon/module/ability → that game's group (`weapons` / `modules` / `abilities`).
- New game → just use a new `--game` name (and whatever `--group` labels fit).
- The command reports `+added` and `skipped` (already present) — relay that.
- After adding, run `.venv/bin/pytest -q` (vocab loads on import) and mention that
  `tags.json` changed so it can be committed.
