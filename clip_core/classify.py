"""Constrained LLM classification: map a free-text description onto the tag vocabulary.

A single `claude` CLI call (Claude Code in print mode) with a JSON-schema-constrained
response whose `tags` field is an enum of the controlled vocabulary. Proposes at most one
new tag only if nothing fits. Running through the `claude` CLI means classification bills
against the logged-in Claude subscription rather than the metered Anthropic API — the CLI
must be installed and authenticated (`claude` on PATH).
"""
from __future__ import annotations

import json
import subprocess
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


def _classification_props(vocab: TagVocab) -> dict:
    """The shared `tags`/`proposed_tag` schema fields (single and batch reuse these)."""
    return {
        "tags": {
            "type": "array",
            "items": {"type": "string", "enum": vocab.as_list()},
        },
        "proposed_tag": {
            "type": ["string", "null"],
            "description": "A single new tag, only if nothing in the vocabulary fits; else null.",
        },
    }


def build_schema(vocab: TagVocab) -> dict:
    return {
        "type": "object",
        "properties": _classification_props(vocab),
        "required": ["tags", "proposed_tag"],
        "additionalProperties": False,
    }


def build_batch_schema(vocab: TagVocab) -> dict:
    """Schema for classifying many clips at once: a `results` array, one entry per id."""
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, **_classification_props(vocab)},
                    "required": ["id", "tags", "proposed_tag"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }


def _claude_cli_runner(*, prompt: str, system: str, schema: dict, model: str) -> dict:
    """Default runner: one non-interactive `claude` call, returning the structured output dict.

    `--allowed-tools NONE` keeps it a single-shot classifier — no agentic tool loop or
    filesystem access, just the schema-constrained answer. The JSON envelope carries the
    already-parsed result under `structured_output` (falling back to the `result` string).
    """
    cmd = [
        "claude",
        "-p",
        "--allowed-tools",
        "NONE",
        "--model",
        model,
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema),
        "--system-prompt",
        system,
    ]
    proc = subprocess.run(cmd, input=prompt, text=True, capture_output=True, check=True)
    envelope = json.loads(proc.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude CLI classification failed: {envelope.get('result')!r}")
    out = envelope.get("structured_output")
    if out is None:
        out = json.loads(envelope["result"])
    return out


def llm_classify(
    description: str,
    vocab: TagVocab,
    *,
    runner=None,
    model: str = "claude-sonnet-4-5",
) -> Classification:
    """Classify one description. Pass `runner` to inject a stub (tests); default shells out to `claude`."""
    if runner is None:
        runner = _claude_cli_runner

    data = runner(
        prompt=f"Description: {description}",
        system=f"{SYSTEM}\n\n# Vocabulary\n{vocab.to_markdown()}",
        schema=build_schema(vocab),
        model=model,
    )
    return Classification(tags=data.get("tags", []), proposed_tag=data.get("proposed_tag"))


BATCH_SYSTEM = (
    "\n\nYou will receive several clips at once, each on its own line as `[id] description`. "
    "Classify every clip independently and return one result object per clip under `results`, "
    "echoing back each clip's exact `id`. Apply the same rules to each."
)


def _chunked(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def llm_classify_batch(
    items: list[tuple[str, str]],
    vocab: TagVocab,
    *,
    runner=None,
    model: str = "claude-sonnet-4-5",
    chunk_size: int = 25,
) -> dict[str, Classification]:
    """Classify many `(id, description)` pairs, sending the vocabulary once per chunk.

    Returns a dict keyed by id. Ids the model omits map to an empty Classification, so the
    caller always gets an entry for every input id. Pass `runner` to inject a stub (tests).
    """
    if runner is None:
        runner = _claude_cli_runner
    system = f"{SYSTEM}{BATCH_SYSTEM}\n\n# Vocabulary\n{vocab.to_markdown()}"
    schema = build_batch_schema(vocab)

    results: dict[str, Classification] = {stem: Classification(tags=[]) for stem, _ in items}
    for chunk in _chunked(items, chunk_size):
        prompt = "\n".join(f"[{stem}] {desc}" for stem, desc in chunk)
        data = runner(prompt=prompt, system=system, schema=schema, model=model)
        for entry in data.get("results", []):
            stem = entry.get("id")
            if stem in results:
                results[stem] = Classification(
                    tags=entry.get("tags", []), proposed_tag=entry.get("proposed_tag")
                )
    return results
