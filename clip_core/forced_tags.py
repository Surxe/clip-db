"""Forced tags: tags applied to clips at ingest regardless of what the classifier says.

A JSON map like the descriptions manifest, but stem -> [tags]. The special key ``"*"``
holds tags forced onto *every* master in the intake -- e.g. pin the game tag for a
single-game batch so you never have to write it into each description and never depend on
the classifier to infer the right game. Written by ``describe.py --force-tag``, read by
``ingest.py``. Kept dumb (just tag strings the human chose); membership against the vocab
is validated where it is consumed.
"""
from __future__ import annotations

import json
from pathlib import Path

from .tags import normalize

ALL = "*"  # batch-wide key: tags forced onto every master in the intake


def load(path) -> dict[str, list[str]]:
    """Return the stem -> [tags] map (normalized, de-duped), or {} if the file is absent."""
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{p}: expected a JSON object of stem -> [tags]")
    out: dict[str, list[str]] = {}
    for k, v in data.items():
        if not isinstance(v, list):
            raise ValueError(f"{p}: value for {k!r} must be a list of tags")
        out[str(k)] = list(dict.fromkeys(normalize(t) for t in v if str(t).strip()))
    return out


def save(path, mapping: dict[str, list[str]]) -> None:
    """Write the manifest, sorted by key for stable diffs."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ordered = {k: mapping[k] for k in sorted(mapping)}
    p.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n")


def for_stem(mapping: dict[str, list[str]], stem: str) -> list[str]:
    """Tags forced onto ``stem``: the batch-wide ``"*"`` set plus any per-stem set."""
    forced = list(mapping.get(ALL, []))
    for t in mapping.get(stem, []):
        if t not in forced:
            forced.append(t)
    return forced
