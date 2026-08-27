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

## Tag relations (aliases + implications)

On top of the flat vocabulary, two optional relation files add *dynamic tag
context*. They are applied by `clip_core.relations.TagRelations` at **classify
time only**, so they affect newly ingested clips and never rewrite existing ones.
`resolve()` runs them in order — normalize aliases, then expand implications:

### Aliases — [`tag_aliases.json`](../tag_aliases.json)
Community nicknames that map to one canonical vocab tag. **This is the file to
view/edit to see the current aliases.** An alias is never itself a tag (it's not
in the enum); it only resolves *to* a canonical tag, and its nicknames are also
shown to the classifier as prompt hints so it recognises them in a description.

```json
{ "games": { "War Robots Frontiers": {
    "aliases": { "Snake Catcher": ["snaketrap", "cage", "trap"] } } } }
```
Keyed **canonical -> [nicknames]** (reads as "Snake Catcher's nicknames are …").

### Implications — [`tag_implications.json`](../tag_implications.json)
A tag implies one or more others (one-directional — tagging the target never adds
the source back). Two sub-maps in this file, both consumed together:

- **`ability_to_module`** — each torso ability adds its module (`snake catcher` ->
  `garuda`). **Generated from game data, not hand-typed** — run
  [`scripts/extract_wrf_implications.py`](../scripts/extract_wrf_implications.py)
  (asserts strictly one-to-one; fails if a game update breaks that). Regenerate on
  a game update alongside the tag refresh.
- **`ability_implies`** — hand-maintained effect implications, one-to-many
  (`optical camo` -> `stealth`, `invis`, `camo`). Edit this by hand.

The extractor only rewrites `ability_to_module`, so `ability_implies` is
**refresh-safe** (preserved across re-extraction).

### Effect tags (hand-maintained groups)
The implication targets above (`stealth`, `reveal`, `silence`, `bubble`, …) are
themselves tags, grouped by hand under the WRF block (`concealment`,
`status effects`, `support fields`). `extract_wrf_tags.py` refreshes only the five
generated groups (weapons/modules/abilities/pilots/pilot talents), so these manual groups
are **refresh-safe** too. Add new effect tags directly to `tags.json`.

Both files are wired through config (`CLIP_ALIASES_PATH`, `CLIP_IMPLICATIONS_PATH`)
and consumed by `ingest.py`; a missing file simply disables that mechanism.

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
they can be regenerated when the game updates.

**On a game update, rerun [`scripts/refresh_wrf_tags.py`](../scripts/refresh_wrf_tags.py)** —
the turnkey wrapper that pulls the source data (`--no-pull` to skip), regenerates the
block via `extract_wrf_tags.py --merge`, prints the per-group tag delta (what was
added/removed), and runs pytest (`--no-tests` to skip). Then review the `tags.json`
diff and commit.

The underlying extractor is [`scripts/extract_wrf_tags.py`](../scripts/extract_wrf_tags.py)
(usable standalone; prints the block to stdout without `--merge`). The extraction logic:

- **Source:** `current/Objects/Module.json`, `Ability.json`, `Pilot.json`, and `PilotTalent.json`.
- **Name field:** each entry's `name.en`.
- **Modules:** only `production_status == "Ready"`, split by `module_type_ref`:
  contains `"Weapon"` → **weapons** group; contains `"Ability"` → **excluded** (an
  ability-slot gadget's module name equals the ability it grants, already listed
  under abilities — so it is not duplicated here); everything else → **modules**
  group (robot chassis / torso / shoulder / Titan body parts).
- **Abilities:** all entries, no status filter → **abilities** group. This already
  covers every torso's granted ability (e.g. the Garuda torso's ability is officially
  *Snake Catcher*, which lands here) — the community nicknames for those abilities
  (snaketrap / cage / trap …) are not in the game data and are handled separately as
  tag aliasing, not extraction.
- **Pilots:** only `Pilot.json` entries whose `pilot_type_ref` ends `Legendary.0` (the 10
  unique named pilots) → **pilots** group. The 72 `Common` pilots are procedurally-named filler
  crew and are excluded. Pilot display names come from `first_name.en`, not `name.en`.
- **Pilot talents:** all `PilotTalent.json` entries, no status filter → **pilot talents** group.
- **Excluded:** `Mk. I` / `Mk. II` variant names (relic/titan tier duplicates).
- Each group is distinct + sorted.
