#!/usr/bin/env python3
"""clip-viewer MCP: query + retrieval over the clip index, served over stdio.

Register this with an MCP client (e.g. Claude Code) as a stdio server. It shares
clip_core with clip-tagger, so the tag vocabulary and query semantics have one definition.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

from mcp.server import MCPServer  # official mcp SDK v2.x (renamed from FastMCP)

from clip_core import index
from clip_core import query as querymod
from clip_core.config import load_config
from clip_core.schema import connect

cfg = load_config()
mcp = MCPServer("clip-viewer")


def _conn():
    return connect(cfg.index_path)


def _clip_dict(c: index.Clip) -> dict:
    return {
        "stem": c.stem,
        "master_path": c.master_path,
        "merged_path": c.merged_path,
        "game": c.game,
        "date": c.date,
        "duration": c.duration,
        "description": c.description,
        "tags": c.tags,
    }


@mcp.tool()
def list_clips(untagged: bool = False) -> list[dict]:
    """List clips. Set untagged=True to return only clips that have no tags yet."""
    conn = _conn()
    clips = index.list_untagged(conn) if untagged else index.all_clips(conn)
    return [_clip_dict(c) for c in clips]


@mcp.tool()
def query(expr: str) -> list[dict]:
    """Query clips by expression, e.g. 'clutch AND valorant', 'game:apex', 'tag:funny'."""
    conn = _conn()
    return [_clip_dict(c) for c in querymod.query(conn, expr)]


@mcp.tool()
def set_tags(stem: str, tags: list[str]) -> dict:
    """Replace all tags on a clip (identified by asset stem)."""
    conn = _conn()
    index.set_tags(conn, stem, tags)
    return _clip_dict(index.get_clip(conn, stem))


@mcp.tool()
def add_tag(stem: str, tag: str) -> dict:
    """Add a single tag to a clip (identified by asset stem)."""
    conn = _conn()
    index.add_tag(conn, stem, tag)
    return _clip_dict(index.get_clip(conn, stem))


if __name__ == "__main__":
    mcp.run()
