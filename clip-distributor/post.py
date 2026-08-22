#!/usr/bin/env python3
"""Post a clip straight to a Discord channel via a webhook -- the headless sibling of
share.py (which stages a file onto the clipboard for a manual paste). This one uploads.

    post.py                       # newest library clip, best-available rendition
    post.py latest                # same as no-arg (explicit)
    post.py "the goblin combo"    # by stem/substring
    post.py /path/to/clip.mp4     # explicit path (rendition, merged, or master)
    post.py -m "clutch 1v3"       # override the message text
    post.py --dry-run             # resolve + compress, but do not upload

DEFAULT PICK (no positional arg): the newest file in the library, taking the first
non-empty tier of, in order,
  1. share renditions  (<stem>_merged_<N>mb.mp4)  -- already compressed, upload-ready,
  2. merged renditions (<stem>_merged.mp4),
  3. masters           (everything else *.mp4).
so a freshly-compressed share rendition wins over the master it came from.

WHATEVER is picked, the upload is guaranteed to fit the cap: a share rendition already
under the cap is sent as-is; anything else (a master, a merged file, or an over-cap
rendition) is run through the same master -> merged -> compress pipeline as share.py
before it goes out. Masters with split audio are mixed on demand into a temp file.

SECRET MODEL: the webhook URL is read from the CLIP_DISCORD_WEBHOOK environment
variable and never from a CLI flag (a URL on argv would leak via `ps`). The real value
lives in ethan's space (~ethan/.config/clip-db/secrets.env, chmod 600) and is injected
into this dev-side run by the ethan-owned `clip-post` launcher; see secrets.env.example.
If the variable is missing, this fails fast before doing any work -- a safe failure.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

from clip_core import media  # noqa: E402
from clip_core.config import load_config  # noqa: E402

from compress import (  # noqa: E402  (sibling module)
    DISCORD_UNBOOSTED_CAP,
    compress_for_share,
    video_budget_kbps,
)
from share import (  # noqa: E402  (sibling module -- reuse the resolve/merge machinery)
    _HEADROOM,
    _AUDIO_KBPS,
    _MIN_VIDEO_KBPS,
    _default_out_dir,
    _share_name,
    ensure_merged,
    is_share_rendition,
    resolve_clip,
)

WEBHOOK_ENV = "CLIP_DISCORD_WEBHOOK"


def tiered_latest(library: Path) -> Path:
    """Newest library clip from the first non-empty tier: share renditions, then merged
    renditions, then masters (see the module docstring)."""
    if not library.is_dir():
        sys.exit(f"library not found: {library} (set CLIP_LIBRARY_DIR)")
    mp4s = list(library.glob("*.mp4"))
    renditions = [f for f in mp4s if is_share_rendition(f)]
    merged = [f for f in mp4s if media.is_merged(f) and not is_share_rendition(f)]
    masters = [f for f in mp4s if media.is_master(f) and not is_share_rendition(f)]
    for tier in (renditions, merged, masters):
        if tier:
            return max(tier, key=lambda f: f.stat().st_mtime)
    sys.exit(f"no clips in {library}")


def clean_title(path) -> str:
    """A human clip name for the default message: the stem with our rendition/merged
    suffixes stripped, so 'the goblin combo_merged_10mb' -> 'the goblin combo'."""
    stem = re.sub(r"_merged_\d+mb$", "", Path(path).stem, flags=re.IGNORECASE)
    return media.stem_of(stem)  # also strips a trailing _merged


def _fmt_mib(n: int) -> str:
    return f"{n / 1024 / 1024:.2f} MiB"


def ensure_shareable(src: Path, args) -> Path:
    """Return a path that fits the cap and is safe to upload.

    A share rendition already under the cap is used as-is. Anything else is run through
    the merge + compress pipeline into <stem>_merged_<cap>mb.mp4 (a real library/out-dir
    file, so re-posts reuse it), with any on-demand audio mix kept to a temp dir.
    """
    if is_share_rendition(src) and src.stat().st_size <= args.cap_bytes:
        return src

    # Feasibility BEFORE the (possibly expensive) merge -- mirror share.py so a clip too
    # long to fit the cap at usable quality fails fast, not after a big mixdown.
    dur = media.probe_duration(src)
    if dur is None:
        sys.exit(f"could not probe duration of {src}")
    if video_budget_kbps(dur, args.cap_bytes, _HEADROOM, _AUDIO_KBPS) < _MIN_VIDEO_KBPS:
        sys.exit(
            f"{src.name}: {dur:.0f}s is too long to fit {_fmt_mib(args.cap_bytes)} at usable "
            f"quality. Trim it, or post to a boosted server (--cap-bytes)."
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    dst = args.out_dir / _share_name(media.stem_of(src), args.cap_bytes)
    with tempfile.TemporaryDirectory(prefix="clip-merge_") as td:
        merged, _is_temp = ensure_merged(src, args.library, Path(td))
        print(f"compressing {merged.name} -> {dst}")
        result = compress_for_share(merged, dst, cap_bytes=args.cap_bytes)
    print(
        f"  {_fmt_mib(result.src_size)} -> {_fmt_mib(result.out_size)} "
        f"({result.out_height}p{result.out_fps:g}, {result.video_kbps}kbps video) "
        f"{'OK under cap' if result.under_cap else 'OVER CAP'}"
    )
    if not result.under_cap:
        sys.exit(f"compressed rendition is still over the cap: {_fmt_mib(result.out_size)}")
    return dst


def post_to_discord(webhook: str, file_path: Path, content: str, username: str | None) -> None:
    """Upload `file_path` to the webhook as a multipart message. Raises on any non-2xx,
    surfacing a 429's retry_after so a rate-limit reads clearly."""
    payload: dict[str, str] = {}
    if content:
        payload["content"] = content[:2000]  # Discord hard-caps message content at 2000 chars
    if username:
        payload["username"] = username

    # wait=true so Discord returns the created message (a 200 with a body) instead of a
    # bare 204 -- gives us a real confirmation and a jump URL to print.
    url = webhook + ("&" if "?" in webhook else "?") + "wait=true"
    with file_path.open("rb") as fh:
        files = {"files[0]": (file_path.name, fh, "video/mp4")}
        data = {"payload_json": json.dumps(payload)} if payload else {}
        # Upload can be slow on a big file / slow link; give it room before timing out.
        resp = httpx.post(url, data=data, files=files, timeout=120.0)

    if resp.status_code == 429:
        try:
            retry = resp.json().get("retry_after")
        except Exception:  # noqa: BLE001
            retry = None
        sys.exit(f"rate limited by Discord (429){f'; retry after {retry}s' if retry else ''}")
    if resp.status_code >= 400:
        sys.exit(f"Discord webhook failed: HTTP {resp.status_code}\n{resp.text[:500]}")

    try:
        body = resp.json()
        cid, mid = body.get("channel_id"), body.get("id")
        where = f" (message {cid}/{mid})" if cid and mid else ""
    except Exception:  # noqa: BLE001
        where = ""
    print(f"  posted to Discord{where}")


def main() -> None:
    cfg = load_config()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("clip", nargs="?", help='a path, a stem/substring, or "latest"; omit for the tiered-latest pick')
    ap.add_argument("-m", "--message", default=None, help="message text (default: the clip's stem)")
    ap.add_argument("--username", default=None, help="override the webhook's display name for this post")
    ap.add_argument("--library", type=Path, default=cfg.library_dir)
    ap.add_argument("--out-dir", type=Path, default=_default_out_dir(cfg.library_dir),
                    help="where a compressed rendition is written (default: the library, or CLIP_SHARE_DIR)")
    ap.add_argument("--cap-bytes", type=int, default=DISCORD_UNBOOSTED_CAP,
                    help="upload size cap in bytes (raise for a boosted server: L2=50MB, L3=100MB)")
    ap.add_argument("--dry-run", action="store_true", help="resolve + compress but do not upload")
    args = ap.parse_args()

    # Fail fast on the secret BEFORE any resolve/compress work -- a missing webhook is a
    # config error, never a reason to have burned an encode. (Skipped for --dry-run.)
    webhook = os.environ.get(WEBHOOK_ENV, "").strip()
    if not webhook and not args.dry_run:
        sys.exit(
            f"{WEBHOOK_ENV} is not set. The webhook URL lives in ethan's "
            f"~/.config/clip-db/secrets.env (chmod 600) and is injected by the `clip-post` "
            f"launcher; see clip-distributor/secrets.env.example. Run via `clip-post`, not directly."
        )

    if args.clip is None or args.clip == "latest":
        src = tiered_latest(args.library)
    else:
        src = resolve_clip(args.clip, args.library)
    print(f"clip: {src.name}")

    upload = ensure_shareable(src, args)
    content = args.message if args.message is not None else clean_title(src)

    if args.dry_run:
        print(f"  [dry-run] would post {upload.name} ({_fmt_mib(upload.stat().st_size)}) "
              f"with message {content!r}")
        print(upload)
        return

    post_to_discord(webhook, upload, content, args.username)
    print(upload)


if __name__ == "__main__":
    main()
