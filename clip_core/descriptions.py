"""The descriptions manifest: a JSON map of asset stem -> one-line description.

This is the per-clip description *input* (blocker §2): `describe` writes it, `ingest`
reads it and classifies. It is keyed by asset stem (`media.stem_of`) so it lines up with
the index, and is deliberately dumb -- just text the human wrote, no tags, no AI.
"""
from __future__ import annotations

import json
from pathlib import Path


def load(path) -> dict[str, str]:
    """Return the stem -> description map, or an empty dict if the file is absent."""
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{p}: expected a JSON object of stem -> description")
    return {str(k): str(v) for k, v in data.items()}


def save(path, mapping: dict[str, str]) -> None:
    """Write the manifest, sorted by stem for stable diffs."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ordered = {k: mapping[k] for k in sorted(mapping)}
    p.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n")
