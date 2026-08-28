"""Grounded answer synthesis over the clip corpus (the G in RAG).

`ask(question, k)` retrieves the semantic top-k clips (Stage 1's `embed.semantic_search`),
feeds them to Claude as grounded context, and returns a synthesised answer that cites the
clip ids (stems) it used. "Grounded" means the model answers from the retrieved candidates
only and says so when none fit -- it cannot invent clips.

Generation reuses the repo's existing LLM path: `classify._claude_cli_runner` (the `claude`
CLI in print mode, schema-constrained, billed against the logged-in subscription -- no API
key). Same runner contract as tag classification; only the prompt, system, and schema differ.
Citations are constrained to an enum of the retrieved stems (mirroring how `classify` pins
`tags` to the vocabulary), so a cited id is always a real, retrieved clip.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import embed, index
from .classify import _claude_cli_runner
from .config import load_config

SYSTEM = (
    "You answer questions about a personal gaming-clip library. You are given a question and "
    "a set of CANDIDATE clips retrieved for it, each as `[stem] game | description | tags`. "
    "Answer using ONLY these candidates -- never invent clips, stems, or facts not present in "
    "them. Identify the clip(s) that answer the question and cite their exact stems in "
    "clip_ids. If none of the candidates actually answer the question, say so plainly and "
    "return an empty clip_ids. Keep the answer to a sentence or two."
)


@dataclass
class Answer:
    answer: str
    clip_ids: list[str]


def build_answer_schema(stems: list[str]) -> dict:
    """Structured-output schema: a free-text answer plus citations pinned to the retrieved
    stems (enum), so the model cannot cite a clip that was not retrieved."""
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "clip_ids": {
                "type": "array",
                "items": {"type": "string", "enum": stems},
                "description": "Stems of the candidate clips that answer the question; empty if none do.",
            },
        },
        "required": ["answer", "clip_ids"],
        "additionalProperties": False,
    }


def _format_candidates(clips: list[index.Clip]) -> str:
    lines = []
    for c in clips:
        game = c.game or "unknown game"
        desc = (c.description or "").strip() or "(no description)"
        tags = ", ".join(c.tags) if c.tags else "(none)"
        lines.append(f"[{c.stem}] {game} | {desc} | tags: {tags}")
    return "\n".join(lines)


def ask(
    conn: sqlite3.Connection,
    question: str,
    k: int,
    *,
    model: str | None = None,
    runner=None,
) -> tuple[Answer, list[index.Clip]]:
    """Retrieve the top-k clips for `question` and synthesise a grounded, cited answer.

    Returns the `Answer` plus the retrieved candidate clips (in rank order) so callers can
    show the context the answer stood on. Pass `runner` to inject a stub (tests); the default
    shells out to the `claude` CLI. Retrieval always runs; generation is skipped (no CLI call)
    when nothing was retrieved.
    """
    hits = embed.semantic_search(conn, question, k)
    candidates = [c for c in (index.get_clip(conn, stem) for stem, _ in hits) if c is not None]

    if not candidates:
        return Answer("No matching clips found in the library.", []), []

    stems = [c.stem for c in candidates]
    if runner is None:
        runner = _claude_cli_runner
    data = runner(
        prompt=f"Question: {question}\n\nCandidate clips:\n{_format_candidates(candidates)}",
        system=SYSTEM,
        schema=build_answer_schema(stems),
        model=model or load_config().model,
    )
    return Answer(answer=data.get("answer", ""), clip_ids=data.get("clip_ids", [])), candidates
