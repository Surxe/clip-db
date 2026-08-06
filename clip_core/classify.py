"""Constrained LLM classification: map a free-text description onto the tag vocabulary.

A single Anthropic call with a JSON-schema-constrained response whose `tags` field is an
enum of the controlled vocabulary. Proposes at most one new tag only if nothing fits.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .tags import TagVocab

SYSTEM = (
    "You map a short free-text description of a gaming clip onto a fixed controlled "
    "vocabulary of tags. Choose only tags from the provided list that genuinely apply "
    "(use meaning, not string overlap: '1v4 retake' -> clutch, 'whiffed everything' -> fail). "
    "The vocabulary is organised into generic tags and per-game sections; when a clip is "
    "from a game, tag it with that game's name plus any specific weapons/modules/abilities "
    "shown. Group headings (weapons, modules, abilities) are organisation only, not tags. "
    "Do not invent tags. Only if nothing in the vocabulary fits, set proposed_tag to a single "
    "concise new tag; otherwise proposed_tag is null."
)


@dataclass
class Classification:
    tags: list[str]
    proposed_tag: str | None = None


def build_schema(vocab: TagVocab) -> dict:
    return {
        "type": "object",
        "properties": {
            "tags": {
                "type": "array",
                "items": {"type": "string", "enum": vocab.as_list()},
            },
            "proposed_tag": {
                "type": ["string", "null"],
                "description": "A single new tag, only if nothing in the vocabulary fits; else null.",
            },
        },
        "required": ["tags", "proposed_tag"],
        "additionalProperties": False,
    }


def llm_classify(
    description: str,
    vocab: TagVocab,
    *,
    client=None,
    model: str = "claude-opus-5",
) -> Classification:
    """Classify one description. Pass `client` to inject a stub (tests); default is a real client."""
    if client is None:
        import anthropic

        client = anthropic.Anthropic()

    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=f"{SYSTEM}\n\n# Vocabulary\n{vocab.to_markdown()}",
        output_config={"format": {"type": "json_schema", "schema": build_schema(vocab)}},
        messages=[{"role": "user", "content": f"Description: {description}"}],
    )
    text = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(text)
    return Classification(tags=data.get("tags", []), proposed_tag=data.get("proposed_tag"))
