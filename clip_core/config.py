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
    model: str


def _path(env: str, default: str) -> Path:
    """Resolve a path env var; relative values resolve against the repo root."""
    value = os.getenv(env, default)
    p = Path(value).expanduser()
    return p if p.is_absolute() else (REPO_ROOT / p)


def load_config() -> Config:
    load_dotenv(override=False)  # populate os.environ from repo .env if present
    return Config(
        intake_dir=_path("CLIP_INTAKE_DIR", "/mnt/os-shared/transfer/clips"),
        library_dir=_path("CLIP_LIBRARY_DIR", "/srv/dev/clips/library"),
        index_path=_path("CLIP_INDEX_PATH", "/srv/dev/clips/index.sqlite"),
        tags_path=_path("CLIP_TAGS_PATH", "tags.json"),
        model=os.getenv("CLIP_MODEL", "claude-opus-5"),
    )
