"""Tag relations layered on top of the controlled vocabulary (see docs/tags.md).

Two mechanisms, applied in order by `resolve()` to a classifier's raw tag list:

1. **Aliases** (`tag_aliases.json`) -- normalization. Community nicknames map to
   one canonical vocab tag: snaketrap / cage / trap -> "snake catcher". An alias is
   NOT itself a vocab tag; it only ever resolves *to* one.
2. **Implications** (`tag_implications.json`) -- expansion. Each torso ability
   implies its module: "snake catcher" -> also add "garuda". One-directional and
   one-to-one (an ability adds its module; a module does not add the ability).

So a clip the model tags with the ability (however it was phrased) ends up carrying
both the ability and its torso module. Expansion is applied at classify time, so it
only affects newly classified clips -- existing clips are never rewritten.

Both files are game-scoped like tags.json but the tag namespace is flat, so this
loader flattens across games into two normalized lookup dicts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .tags import normalize


@dataclass(frozen=True)
class TagRelations:
    # alias (normalized) -> canonical tag (normalized)
    aliases: dict[str, str] = field(default_factory=dict)
    # ability tag (normalized) -> module tag it implies (normalized)
    implications: dict[str, str] = field(default_factory=dict)
    # canonical tag (normalized) -> its nicknames (normalized), for prompt hints
    alias_groups: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, aliases_path=None, implications_path=None) -> "TagRelations":
        aliases: dict[str, str] = {}
        alias_groups: dict[str, list[str]] = {}
        for canonical, nicks in _iter_game_block(aliases_path, "aliases").items():
            canon = normalize(canonical)
            names = [normalize(n) for n in nicks if n.strip()]
            alias_groups.setdefault(canon, [])
            for nick in names:
                aliases[nick] = canon
                if nick not in alias_groups[canon]:
                    alias_groups[canon].append(nick)

        implications = {
            normalize(ability): normalize(module)
            for ability, module in _iter_game_block(implications_path, "ability_to_module").items()
        }
        return cls(aliases=aliases, implications=implications, alias_groups=alias_groups)

    def resolve(self, tags: list[str]) -> list[str]:
        """Normalize aliases, then expand ability implications; de-dupe, order-preserving."""
        out: list[str] = []
        for tag in tags:
            canonical = self.aliases.get(normalize(tag), normalize(tag))
            for resolved in (canonical, self.implications.get(canonical)):
                if resolved and resolved not in out:
                    out.append(resolved)
        return out

    def hint_markdown(self) -> str:
        """Nickname hints for the classifier prompt.

        Aliases are not in the enum, so the model cannot emit them; telling it what
        the nicknames mean lets it map a nickname seen in a description onto the
        canonical tag. Empty string when there are no aliases.
        """
        if not self.alias_groups:
            return ""
        lines = [
            "## Ability nicknames",
            "Community nicknames that may appear in descriptions -- map each to the "
            "canonical tag on its left (the nickname itself is never a tag):",
        ]
        for canonical, nicks in self.alias_groups.items():
            if nicks:
                lines.append(f"- {canonical}: {', '.join(nicks)}")
        return "\n".join(lines)


def _iter_game_block(path, key: str) -> dict:
    """Merge every game's `key` sub-object from a game-scoped relations file.

    Missing path/file yields an empty dict, so relations are always optional.
    """
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    merged: dict = {}
    for gdef in data.get("games", {}).values():
        merged.update((gdef or {}).get(key, {}))
    return merged
