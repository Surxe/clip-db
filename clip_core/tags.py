"""Controlled tag vocabulary loaded from tags.json."""
from __future__ import annotations

import json
from pathlib import Path


def normalize(tag: str) -> str:
    return tag.strip().lower()


class TagVocab:
    """An ordered, de-duplicated, normalized set of allowed tags."""

    def __init__(self, tags: list[str]):
        self._ordered = list(dict.fromkeys(normalize(t) for t in tags if t.strip()))
        self._set = set(self._ordered)

    def __contains__(self, tag: str) -> bool:
        return normalize(tag) in self._set

    def __iter__(self):
        return iter(self._ordered)

    def __len__(self) -> int:
        return len(self._ordered)

    def as_list(self) -> list[str]:
        return list(self._ordered)


def load_vocab(path) -> TagVocab:
    data = json.loads(Path(path).read_text())
    tags = data["tags"] if isinstance(data, dict) else data
    return TagVocab(tags)
