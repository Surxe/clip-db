# Tag vocabulary

The controlled vocabulary lives in [`tags.json`](../tags.json). The classifier
(`clip_core.classify`) can only emit tags from this file — its JSON-schema `enum`
is built directly from the flattened vocabulary, so nothing outside it can be
assigned (the model may only *propose* a new tag via `proposed_tag`).

## Two tiers

### 1. Generic tags
Cross-game descriptors that apply to any clip: `clutch`, `fail`, `highlight`,
`funny`, `teamplay`, `ace`, … These are meant to grow large.

```json
{ "generic": ["clutch", "fail", "highlight", "funny", "teamplay", "ace"] }
```

### 2. Game tags
Everything specific to one game lives under `games`, keyed by the game's display
name. Two rules define what becomes a tag:

- **The game name is a tag.** `"War Robots Frontiers"` → tag `war robots frontiers`.
- **Every item is a tag.** Each weapon / module / ability name is a tag.

Items are organised into named **groups** purely for readability and to help the
classifier reason (e.g. "tag the weapon shown"). **Group labels are NOT tags** —
`weapons`, `modules`, `abilities` are organisation only and never assignable.

```json
{
  "games": {
    "War Robots Frontiers": {
      "groups": {
        "weapons":   ["Apollo", "Zeus", "..."],
        "modules":   ["Aegis", "..."],
        "abilities": ["Ammo Fabricator", "..."]
      }
    }
  }
}
```

## How it's consumed

`clip_core.tags.load_vocab()` reads `tags.json` and produces a `TagVocab` that
carries **both** representations from one source of truth:

- **Flat list** — generic + every game name + every item, normalized
  (`strip().lower()`) and de-duplicated. This is the schema `enum` and the
  membership set. Items shared across groups (a weapon that shares a name with its
  ability) collapse to one tag.
- **Structure** — the generic list and the per-game groups, preserved so
  `TagVocab.to_markdown()` can render a grouped view.

At classify time the model is shown the **Markdown** view (grouped, with headings),
not a flat comma list — grouping improves game/item disambiguation — while the
**enum** still constrains output to exact strings. The Markdown is generated in
memory from `tags.json`; it is never a hand-maintained artifact.

`load_vocab` also still accepts the legacy `{"tags": [...]}` and bare-list shapes.

## Normalization / constraints

- Tags are normalized to `strip().lower()` everywhere (vocab, index, query), so
  `tags.json` may use nice display casing (`"War Robots Frontiers"`, `"Apollo"`);
  it is lowercased on load.
- The SQLite index stores a clip's tags comma-joined, so **a tag must not contain a
  comma**. The extraction script asserts this.

## Adding a new game

1. Add a top-level key under `games` with the game's display name.
2. Add a `groups` object. Choose whatever group labels read well for that game
   (they need not be weapons/modules/abilities — e.g. `agents`, `maps`, `operators`).
   Group labels are for humans and the prompt only.
3. List the item names under each group. The game name and every item automatically
   become tags; labels do not.
4. Run the tests (`.venv/bin/pytest`) — the vocab loads and flattens on import.

No code changes are required to add a game — the reader is data-driven.

### War Robots Frontiers specifics
The WRF lists are extracted from the `WRFrontiersDB-Data` repo, not hand-typed, so
they can be regenerated when the game updates. See
[`scripts/extract_wrf_tags.py`](../scripts/extract_wrf_tags.py). The extraction logic:

- **Source:** `current/Objects/Module.json` and `current/Objects/Ability.json`.
- **Name field:** each entry's `name.en`.
- **Modules:** only `production_status == "Ready"`. Split by `module_type_ref`:
  contains `"Weapon"` → **weapons** group; otherwise → **modules** group
  (chassis / torso / shoulder / ability-slot / Titan body parts).
- **Abilities:** all entries, no status filter → **abilities** group.
- **Excluded:** `Mk. I` / `Mk. II` variant names (relic/titan tier duplicates).
- Each group is distinct + sorted.
