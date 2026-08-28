"""Configuration loaded from .env (or the environment). Paths only — no secrets committed."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    intake_dir: Path
    library_dir: Path
    index_path: Path
    tags_path: Path
    aliases_path: Path
    implications_path: Path
    descriptions_path: Path
    discord_queue_dir: Path
    model: str
    embed_model: str
    semantic_top_k: int
    auto_merge_max_seconds: int
    forced_tags_path: Path | None = None


def _path(env: str, default: str) -> Path:
    """Resolve a path env var; relative values resolve against the repo root."""
    value = os.getenv(env, default)
    p = Path(value).expanduser()
    return p if p.is_absolute() else (REPO_ROOT / p)


def load_config() -> Config:
    load_dotenv(override=False)  # populate os.environ from repo .env if present
    intake_dir = _path("CLIP_INTAKE_DIR", "/mnt/os-shared/transfer/clips")
    return Config(
        intake_dir=intake_dir,
        library_dir=_path("CLIP_LIBRARY_DIR", "/srv/dev/clips/library"),
        index_path=_path("CLIP_INDEX_PATH", "/srv/dev/clips/index.sqlite"),
        tags_path=_path("CLIP_TAGS_PATH", "tags.json"),
        aliases_path=_path("CLIP_ALIASES_PATH", "tag_aliases.json"),
        implications_path=_path("CLIP_IMPLICATIONS_PATH", "tag_implications.json"),
        descriptions_path=_path("CLIP_DESCRIPTIONS_PATH", str(intake_dir / "descriptions.json")),
        discord_queue_dir=_path("CLIP_DISCORD_QUEUE_DIR", "/srv/dev/clips/discord-queue"),
        model=os.getenv("CLIP_MODEL", "claude-sonnet-4-5"),
        embed_model=os.getenv("CLIP_EMBED_MODEL", "all-MiniLM-L6-v2"),
        semantic_top_k=int(os.getenv("CLIP_SEMANTIC_TOP_K", "5")),
        auto_merge_max_seconds=int(os.getenv("CLIP_AUTO_MERGE_MAX_SECONDS", "120")),
        forced_tags_path=_path("CLIP_FORCED_TAGS_PATH", str(intake_dir / "forced_tags.json")),
    )
