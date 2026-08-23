#!/usr/bin/env python3
"""clip-viewer MCP: query, retrieval, and dev-side media prep over the clip index,
served over stdio.

Register this with an MCP client (e.g. Claude Code) as a stdio server. It shares
clip_core with clip-tagger, so the tag vocabulary and query semantics have one definition.

The media-prep tools (merge_audio, prepare_share) do only DEV-side work on the dev-owned
library. They deliberately stop short of delivery: copying to the clipboard and posting
to a Discord webhook are ethan-side (the clipboard belongs to ethan's desktop session,
and the webhook secret is ethan-owned and unreadable by dev). prepare_share therefore
returns a ready file plus the `clip-post` command for ethan to run.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))                          # repo root on sys.path
sys.path.insert(0, str(_REPO / "clip-distributor"))     # sibling distributor modules

from mcp.server import MCPServer  # official mcp SDK v2.x (renamed from FastMCP)

from clip_core import discord_queue
from clip_core import index
from clip_core import merge as coremerge
from clip_core import query as querymod
from clip_core.config import load_config
from clip_core.schema import connect

from compress import compress_for_share  # clip-distributor sibling
from share import _default_out_dir, _share_name  # clip-distributor sibling

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
    """Query clips by expression, e.g. 'clutch AND valorant', 'game:apex', 'tag:funny'.

    A bare term matches a tag or the game; prefixes narrow it (tag:, game:, date:).
    Tags may contain spaces — write them bare ('movement tech') or quoted
    ('tag:"fuel thief"'); both work. AND/OR combine terms left-to-right.
    """
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


def _clip_or_raise(conn, stem: str) -> index.Clip:
    clip = index.get_clip(conn, stem)
    if clip is None:
        raise ValueError(f"no indexed clip with stem {stem!r}")
    return clip


@mcp.tool()
def merge_audio(stem: str, force: bool = False) -> dict:
    """Mix a clip's split audio tracks into its _merged.mp4 and attach it to the index.

    Idempotent: an existing merged rendition is reused unless force=True. Pure dev-side
    work on the library — no clipboard or Discord (those are ethan-side, see prepare_share).
    """
    conn = _conn()
    clip = _clip_or_raise(conn, stem)
    r = coremerge.merge_master(conn, clip.master_path, force=force)
    return {"stem": r.stem, "status": r.status, "merged_path": r.merged_path}


@mcp.tool()
def prepare_share(stem: str, cap_mb: int = 10, compress: bool = True, force: bool = False) -> dict:
    """Produce an upload-ready rendition of a clip and return its path.

    Always mixes the split audio into a _merged.mp4 first (reusing an existing one unless
    force). Then:
      - compress=True (default): transcode that down to fit cap_mb (10 MiB = the unboosted
        Discord limit) as <stem>_merged_<cap>mb.mp4 — use for a normal server or a manual
        paste into an unboosted server.
      - compress=False: return the merged file uncompressed — for a Nitro-boosted server
        where the size cap is high and re-encoding is unnecessary.

    Dev-side media prep ONLY. Delivery is ethan-side: paste the returned path into Discord,
    or send it with the returned `clip_post_cmd` (`clip-post "<path>"`).
    """
    conn = _conn()
    clip = _clip_or_raise(conn, stem)
    merged = coremerge.merge_master(conn, clip.master_path, force=force)

    if not compress:
        return {
            "stem": merged.stem,
            "merged_path": merged.merged_path,
            "compressed": False,
            "note": "merged only (uncompressed) — for a boosted server; paste it into Discord directly",
        }

    cap_bytes = cap_mb * 1024 * 1024
    out_dir = Path(_default_out_dir(cfg.library_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / _share_name(merged.stem, cap_bytes)
    result = compress_for_share(merged.merged_path, dst, cap_bytes=cap_bytes)
    return {
        "stem": merged.stem,
        "merged_path": merged.merged_path,
        "share_path": str(result.dst),
        "compressed": True,
        "under_cap": result.under_cap,
        "src_size": result.src_size,
        "out_size": result.out_size,
        "cap_bytes": cap_bytes,
        "out_height": result.out_height,
        "out_fps": result.out_fps,
        "video_kbps": result.video_kbps,
        "clip_post_cmd": f'clip-post "{result.dst}"',
    }


@mcp.tool()
def queue_discord_post(stem: str, message: str | None = None, cap_mb: int = 10) -> dict:
    """Queue a clip to be posted to Discord via the webhook — usable from any Claude
    client (e.g. the phone), since the whole thing runs on the dev box.

    dev can't post to Discord itself (the webhook secret is ethan-owned and unreadable
    by dev), so this does the dev-side prep — merge + compress to fit cap_mb (10 MiB =
    the unboosted limit) — then drops a job in the spool queue. An ethan-side watcher
    consumes the queue and does the actual upload with `clip-post`. If the clip is too
    long to fit the cap, that error surfaces HERE (before queueing), so you get immediate
    feedback rather than a silent failure in the watcher.

    Returns the queued job path and the prepared file. The post itself happens
    asynchronously once the watcher picks the job up.
    """
    conn = _conn()
    clip = _clip_or_raise(conn, stem)
    merged = coremerge.merge_master(conn, clip.master_path, force=False)

    cap_bytes = cap_mb * 1024 * 1024
    out_dir = Path(_default_out_dir(cfg.library_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / _share_name(merged.stem, cap_bytes)
    result = compress_for_share(merged.merged_path, dst, cap_bytes=cap_bytes)
    if not result.under_cap:
        raise ValueError(
            f"compressed rendition is still over the {cap_mb} MiB cap "
            f"({result.out_size} bytes) — trim the clip or raise cap_mb (boosted server)"
        )

    job = discord_queue.enqueue(cfg.discord_queue_dir, result.dst, message=message, cap_mb=cap_mb)
    return {
        "stem": merged.stem,
        "queued": True,
        "job_file": str(job),
        "share_path": str(result.dst),
        "out_size": result.out_size,
        "under_cap": result.under_cap,
        "message": message,
        "note": "queued for the ethan-side watcher to post via clip-post; upload happens asynchronously",
    }


if __name__ == "__main__":
    mcp.run()
