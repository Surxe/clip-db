"""Controlled tag vocabulary loaded from tags.json.

The vocabulary has two tiers (see docs/tags.md):

* **generic** tags apply to any game (clutch, fail, ...).
* **game** tags live under a named game. The game's display name is itself a tag,
  and every item under it is a tag. Items are organised into named *groups*
  (e.g. weapons / modules / abilities) purely for readability — the group labels
  are NOT tags.

`TagVocab` exposes a single flat, normalized, de-duplicated list (used verbatim as
the JSON-schema enum the classifier is constrained to) while retaining the grouped
structure so it can be rendered to Markdown for the classifier's prompt.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


def normalize(tag: str) -> str:
    return tag.strip().lower()


@dataclass(frozen=True)
class Game:
    """One game's tags: the game name (a tag) plus labelled groups of item tags."""

    name: str                       # normalized game tag, e.g. "war robots frontiers"
    groups: dict[str, list[str]]    # label -> normalized item tags (order preserved)

    def all_tags(self) -> list[str]:
        tags = [self.name]
        for items in self.groups.values():
            tags.extend(items)
        return tags


class TagVocab:
    """An ordered, de-duplicated, normalized set of allowed tags.

    Construct with a bare list of tags (structureless), or via `load_vocab` /
    `from_structure` to carry the generic + per-game grouping used for rendering.
    """

    def __init__(
        self,
        tags: list[str],
        *,
        generic: list[str] | None = None,
        games: list[Game] | None = None,
    ):
        self._ordered = list(dict.fromkeys(normalize(t) for t in tags if t.strip()))
        self._set = set(self._ordered)
        self.generic = list(dict.fromkeys(normalize(t) for t in (generic or []) if t.strip()))
        self.games = games or []

    def __contains__(self, tag: str) -> bool:
        return normalize(tag) in self._set

    def __iter__(self):
        return iter(self._ordered)

    def __len__(self) -> int:
        return len(self._ordered)

    def as_list(self) -> list[str]:
        return list(self._ordered)

    @classmethod
    def from_structure(cls, generic: list[str], games: list[Game]) -> "TagVocab":
        flat: list[str] = list(generic)
        for game in games:
            flat.extend(game.all_tags())
        return cls(flat, generic=generic, games=games)

    def to_markdown(self) -> str:
        """Render the vocabulary as Markdown for the classifier's system prompt.

        Uses the same normalized strings that appear in the enum, so what the model
        reads is exactly what it is allowed to emit. Grouping/headings are context only.
        """
        lines: list[str] = []
        if self.generic:
            lines.append("## Generic tags (any game)")
            lines.append(", ".join(self.generic))
        for game in self.games:
            lines.append("")
            lines.append(f"## {game.name}")
            lines.append(f'(the game name "{game.name}" is itself a tag)')
            for label, items in game.groups.items():
                if items:
                    lines.append(f"- **{label}**: {', '.join(items)}")
        # Structureless vocab (bare list): just list everything.
        if not self.generic and not self.games:
            lines.append(", ".join(self._ordered))
        return "\n".join(lines)


def _load_games(games_obj: dict) -> list[Game]:
    games: list[Game] = []
    for game_name, gdef in games_obj.items():
        groups_obj = (gdef or {}).get("groups", {})
        groups = {
            label: list(dict.fromkeys(normalize(t) for t in items if t.strip()))
            for label, items in groups_obj.items()
        }
        games.append(Game(name=normalize(game_name), groups=groups))
    return games


def load_vocab(path) -> TagVocab:
    """Load tags.json. Accepts three shapes:

    1. Structured:  {"generic": [...], "games": {"<Game>": {"groups": {"<label>": [...]}}}}
    2. Legacy dict: {"tags": [...]}
    3. Bare list:   [...]
    """
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict) and ("generic" in data or "games" in data):
        generic = [normalize(t) for t in data.get("generic", [])]
        games = _load_games(data.get("games", {}))
        return TagVocab.from_structure(generic, games)
    tags = data["tags"] if isinstance(data, dict) else data
    return TagVocab(tags)
