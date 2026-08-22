#!/usr/bin/env python3
"""Standalone share caller: compress a library clip under the Discord cap, then put
the result on the clipboard as a *file* so it can be pasted/attached into Discord.

    share.py latest                       # newest merged master in the library
    share.py "the goblin combo"           # by stem/substring (merged master preferred)
    share.py /path/to/anything_merged.mp4  # explicit path
    share.py latest --no-clipboard        # just compress
    share.py latest --reveal              # also open the folder for drag-drop

Runs the size-target transcode (compress.compress_for_share), writes the output to a
share dir (CLIP_SHARE_DIR, default ~/clip-share -- a transport dir, not the library),
and copies it to the clipboard.

CLIPBOARD NOTE: this must run inside your own desktop session (needs WAYLAND_DISPLAY +
XDG_RUNTIME_DIR), as the user that owns that session -- the clipboard is per-user. It
advertises the file as `text/uri-list` via wl-copy, which is how KDE/Dolphin put a file
on the clipboard; Discord attaches it on Ctrl+V. If a Discord build pastes the path as
text instead, use --reveal and drag the file in from the file manager.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from shutil import which

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

from clip_core import media  # noqa: E402
from clip_core.config import load_config  # noqa: E402

from compress import compress_for_share, DISCORD_UNBOOSTED_CAP  # noqa: E402  (sibling module)


def _default_share_dir() -> Path:
    return Path(os.environ.get("CLIP_SHARE_DIR", str(Path.home() / "clip-share")))


def resolve_clip(arg: str, library: Path) -> Path:
    """Resolve the input to a concrete file.

    - an existing path -> itself
    - "latest"         -> newest *_merged.mp4 in the library by mtime
    - a stem/substring -> matching master, preferring the *_merged.mp4
    """
    p = Path(arg).expanduser()
    if p.exists():
        return p

    if not library.is_dir():
        sys.exit(f"library not found: {library} (set CLIP_LIBRARY_DIR)")

    merged = sorted(
        (f for f in library.glob("*.mp4") if media.is_merged(f)),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if arg == "latest":
        if not merged:
            sys.exit(f"no *_merged.mp4 clips in {library}")
        return merged[0]

    key = arg.lower().removesuffix(".mp4")
    # Prefer a merged master whose stem contains the key; fall back to any mp4.
    for f in merged:
        if key in f.stem.lower():
            return f
    for f in sorted(library.glob("*.mp4")):
        if key in f.stem.lower():
            return f
    sys.exit(f"no clip matching {arg!r} in {library}")


def copy_file_to_clipboard(path: Path) -> None:
    """Put `path` on the clipboard as a file (text/uri-list) via wl-copy (Wayland).

    wl-copy daemonizes to keep serving the selection until it is replaced, so the
    file stays pasteable after this process exits.
    """
    if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("XDG_RUNTIME_DIR"):
        raise RuntimeError(
            "no Wayland session in this shell (WAYLAND_DISPLAY/XDG_RUNTIME_DIR unset) "
            "-- run this inside your desktop session, as the session's user"
        )
    if not which("wl-copy"):
        raise RuntimeError("wl-copy not found (install wl-clipboard)")
    uri = path.resolve().as_uri()
    # text/uri-list wants CRLF-terminated URIs.
    subprocess.run(
        ["wl-copy", "--type", "text/uri-list"],
        input=(uri + "\r\n").encode(),
        check=True,
    )


def reveal(path: Path) -> None:
    """Open the containing folder in the file manager for manual drag-drop."""
    opener = ["dolphin", "--select", str(path)] if which("dolphin") else ["xdg-open", str(path.parent)]
    subprocess.Popen(opener, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _fmt_mib(n: int) -> str:
    return f"{n / 1024 / 1024:.2f} MiB"


def main() -> None:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip", help='library clip: a path, a stem/substring, or "latest"')
    ap.add_argument("--out-dir", type=Path, default=_default_share_dir(), help="where to write the compressed file")
    ap.add_argument("--library", type=Path, default=cfg.library_dir)
    ap.add_argument("--cap-bytes", type=int, default=DISCORD_UNBOOSTED_CAP)
    ap.add_argument("--no-clipboard", action="store_true", help="compress only, don't touch the clipboard")
    # Dolphin is off by default (clipboard is the happy path); --reveal opts into it,
    # --no-reveal is the explicit off-switch.
    ap.add_argument("--reveal", action=argparse.BooleanOptionalAction, default=False,
                    help="open the folder in the file manager for drag-drop (default: no)")
    args = ap.parse_args()

    src = resolve_clip(args.clip, args.library)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    # Strip the _merged suffix from the share copy's name; it's a transport artifact.
    stem = src.stem.removesuffix("_merged")
    dst = args.out_dir / f"{stem}_share.mp4"

    print(f"compressing {src.name} -> {dst}")
    result = compress_for_share(src, dst, cap_bytes=args.cap_bytes)
    print(
        f"  {_fmt_mib(result.src_size)} -> {_fmt_mib(result.out_size)} "
        f"({result.out_height}p{result.out_fps:g}, {result.video_kbps}kbps video) "
        f"{'OK under cap' if result.under_cap else 'OVER CAP'}"
    )

    if not args.no_clipboard:
        try:
            copy_file_to_clipboard(dst)
            print("  copied to clipboard (paste into Discord with Ctrl+V)")
        except Exception as e:  # noqa: BLE001 -- surface, don't lose the compress result
            print(f"  clipboard skipped: {e}")
            print(f"  file is ready at: {dst}")

    if args.reveal:
        reveal(dst)

    print(dst)


if __name__ == "__main__":
    main()
