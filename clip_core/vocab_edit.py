"""Bulk edits to the tag vocabulary (tags.json). One source of truth for both the
`add_tags` CLI/skill and the interactive `review` step.

Insertion is idempotent and case-insensitive on dedupe, rejects commas (the index
delimiter), preserves display casing, and keeps game groups sorted. Generic tags keep
their append order.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TAGS_JSON = REPO_ROOT / "tags.json"
IMPLICATIONS_JSON = REPO_ROOT / "tag_implications.json"
ALIASES_JSON = REPO_ROOT / "tag_aliases.json"

# Hand-maintained implication sub-key (see clip_core.relations). `ability_to_module` is
# generated from game data and must not be hand-edited, so seeding lands here.
IMPLIES_KEY = "ability_implies"


def _write_json(data: dict, path) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def load_tags(path=TAGS_JSON) -> dict:
    data = json.loads(Path(path).read_text())
    data.setdefault("generic", [])
    data.setdefault("games", {})
    return data


def save_tags(data: dict, path=TAGS_JSON) -> None:
    _write_json(data, path)


def load_relations(path) -> dict:
    """Load a game-scoped relations file (aliases or implications). Missing -> empty."""
    p = Path(path)
    data = json.loads(p.read_text()) if p.exists() else {}
    data.setdefault("games", {})
    return data


def save_relations(data: dict, path) -> None:
    _write_json(data, path)


def _add(existing: list[str], new: list[str], *, sort: bool) -> tuple[list[str], list[str], list[str]]:
    """Merge `new` into `existing`. Returns (result, added, skipped). Comma -> ValueError."""
    have = {t.lower() for t in existing}
    added, skipped = [], []
    for t in new:
        t = t.strip()
        if not t:
            continue
        if "," in t:
            raise ValueError(f"tag {t!r} contains a comma (illegal -- comma is the index delimiter)")
        (skipped if t.lower() in have else added).append(t)
        have.add(t.lower())
    result = existing + added
    if sort:
        result = sorted(dict.fromkeys(result), key=str.lower)
    return result, added, skipped


def add_generic(data: dict, tags: list[str]) -> tuple[list[str], list[str]]:
    """Add cross-game generic tags (append order). Returns (added, skipped)."""
    data["generic"], added, skipped = _add(data["generic"], tags, sort=False)
    return added, skipped


def add_game_group(data: dict, game: str, group: str, tags: list[str]) -> tuple[list[str], list[str]]:
    """Add item tags under game/group (both created if missing; group stays sorted)."""
    groups = data["games"].setdefault(game, {}).setdefault("groups", {})
    groups[group], added, skipped = _add(groups.get(group, []), tags, sort=True)
    return added, skipped


def add_implication(data: dict, game: str, source: str, targets: list[str]) -> tuple[list[str], list[str]]:
    """Add `source implies targets` under game's hand-maintained block (append order).

    `data` is a relations dict (see load_relations). The game block and IMPLIES_KEY are
    created if missing; an existing single-string value is promoted to a list. Returns
    (added, skipped) targets. Applied to a clip's tags at tag time via relations.resolve.
    """
    source = source.strip()
    if not source:
        raise ValueError("implication source is empty")
    if "," in source:
        raise ValueError(f"source {source!r} contains a comma (illegal -- comma is the index delimiter)")
    block = data["games"].setdefault(game, {}).setdefault(IMPLIES_KEY, {})
    existing = block.get(source, [])
    if isinstance(existing, str):
        existing = [existing]
    block[source], added, skipped = _add(existing, targets, sort=False)
    return added, skipped


def add_alias(data: dict, game: str, canonical: str, nicks: list[str]) -> tuple[list[str], list[str]]:
    """Add nickname aliases for a canonical tag under game (append order).

    `data` is a relations dict (see load_relations). The game block and its `aliases`
    map are created if missing. Nicknames resolve *to* the canonical tag; they are not
    themselves vocab tags. Returns (added, skipped) nicknames.
    """
    canonical = canonical.strip()
    if not canonical:
        raise ValueError("alias canonical is empty")
    if "," in canonical:
        raise ValueError(f"canonical {canonical!r} contains a comma (illegal -- comma is the index delimiter)")
    aliases = data["games"].setdefault(game, {}).setdefault("aliases", {})
    aliases[canonical], added, skipped = _add(aliases.get(canonical, []), nicks, sort=False)
    return added, skipped
