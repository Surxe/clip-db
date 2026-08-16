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


def load_tags(path=TAGS_JSON) -> dict:
    data = json.loads(Path(path).read_text())
    data.setdefault("generic", [])
    data.setdefault("games", {})
    return data


def save_tags(data: dict, path=TAGS_JSON) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


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
