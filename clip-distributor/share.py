#!/usr/bin/env python3
"""Share a clip to Discord: pick a library master, merge its audio if needed, compress
it under the upload cap, and put the result on the clipboard as a *file* to paste in.

    share.py                              # pick from the library (kdialog dialog)
    share.py latest                       # newest merged master, no prompt
    share.py "the goblin combo"           # by stem/substring
    share.py /path/to/anything.mp4        # explicit path (master or merged)
    share.py --pick                       # force the picker
    share.py latest --no-clipboard        # just compress
    share.py latest --reveal              # also open the folder for drag-drop

Orchestrates the full master -> shareable path:
  1. resolve a clip (picker / "latest" / stem / path),
  2. if it's a split-audio master with no merged rendition, mix one on demand
     (clip_core.media.regenerate_merged) -- a temp intermediate, cleaned up after,
  3. compress the merged rendition under the cap (compress.compress_for_share),
  4. copy the compressed file to the clipboard.

CLIPBOARD NOTE: this must run inside your own desktop session (needs WAYLAND_DISPLAY +
XDG_RUNTIME_DIR), as the user that owns that session -- the clipboard is per-user. It
advertises the file as `text/uri-list` via wl-copy, which is how KDE/Dolphin put a file
on the clipboard; Discord attaches it on Ctrl+V. If a Discord build pastes the path as
text instead, use --reveal and drag the file in from the file manager.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from shutil import which

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

from clip_core import media  # noqa: E402
from clip_core.config import load_config  # noqa: E402

from compress import (  # noqa: E402  (sibling module)
    DISCORD_UNBOOSTED_CAP,
    compress_for_share,
    video_budget_kbps,
)

# Must match compress_for_share's defaults so the pre-merge feasibility check agrees
# with what the actual encode would accept.
_HEADROOM, _AUDIO_KBPS, _MIN_VIDEO_KBPS = 0.90, 96, 350


# Our compressed share renditions look like <stem>_merged_10mb.mp4. That name does NOT
# end in "_merged", so clip_core.media.is_master() treats it as a master -- exclude it
# explicitly so our own outputs don't masquerade as source clips in the picker.
_SHARE_RE = re.compile(r"_merged_\d+mb$", re.IGNORECASE)


def is_share_rendition(path) -> bool:
    return bool(_SHARE_RE.search(Path(path).stem))


def _share_name(stem: str, cap_bytes: int) -> str:
    """<stem>_merged_<cap>mb.mp4 -- the compressed rendition, tagged with its cap."""
    return f"{stem}_merged_{cap_bytes // (1024 * 1024)}mb.mp4"


def _default_out_dir(cfg_library: Path) -> Path:
    return Path(os.environ["CLIP_SHARE_DIR"]) if os.environ.get("CLIP_SHARE_DIR") else cfg_library


def _masters_newest_first(library: Path) -> list[Path]:
    return sorted(
        (f for f in library.glob("*.mp4") if media.is_master(f) and not is_share_rendition(f)),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )


def pick_master(library: Path) -> Path:
    """Pick a clip from the library: a graphical kdialog dialog when a desktop session
    is present, otherwise a terminal list (newest first)."""
    if not library.is_dir():
        sys.exit(f"library not found: {library} (set CLIP_LIBRARY_DIR)")
    have_display = bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))
    if have_display and which("kdialog"):
        return _pick_kdialog(library)
    return _pick_terminal(library)


def _pick_kdialog(library: Path) -> Path:
    """KDE file dialog showing masters only. kdialog's filter is include-only and can't
    exclude our _merged / _merged_<N>mb renditions, so the dialog is rooted at a temp
    dir of symlinks to just the masters; the pick is resolved back to the real file."""
    masters = _masters_newest_first(library)  # excludes _merged and _merged_<N>mb
    if not masters:
        sys.exit(f"no master clips in {library}")
    with tempfile.TemporaryDirectory(prefix="clip-pick_") as td:
        tdp = Path(td)
        for f in masters:
            (tdp / f.name).symlink_to(f)
        r = subprocess.run(
            ["kdialog", "--title", "Share clip: pick a master",
             "--getopenfilename", str(tdp), "*.mp4|Clips (*.mp4)"],
            capture_output=True, text=True,
        )
        path = r.stdout.strip()
        if r.returncode != 0 or not path:
            sys.exit("no clip selected")
        return Path(path).resolve()  # symlink -> real library file (before tempdir cleanup)


def _pick_terminal(library: Path) -> Path:
    """Fallback picker for headless shells: library masters, newest first, Enter = #1."""
    masters = _masters_newest_first(library)
    if not masters:
        sys.exit(f"no master clips in {library}")

    print(f"clips in {library} (newest first):")
    for i, f in enumerate(masters, 1):
        st = f.stat()
        when = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"  {i:>2}. {when}  {st.st_size / 1024 / 1024:6.0f} MB  {f.name}")

    try:
        raw = input("select clip [1]: ").strip() or "1"
    except EOFError:
        sys.exit("no selection (not a tty)")
    if not raw.isdigit() or not (1 <= int(raw) <= len(masters)):
        sys.exit(f"invalid selection: {raw!r}")
    return masters[int(raw) - 1]


def resolve_clip(arg: str, library: Path) -> Path:
    """Resolve a non-picker argument to a concrete file.

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
    for f in merged:  # prefer a merged master whose stem contains the key
        if key in f.stem.lower():
            return f
    for f in sorted(library.glob("*.mp4")):  # fall back to any mp4
        if key in f.stem.lower():
            return f
    sys.exit(f"no clip matching {arg!r} in {library}")


def ensure_merged(src: Path, library: Path, workdir: Path) -> tuple[Path, bool]:
    """Return a single-audio (merged) rendition of `src` and whether it's a temp file.

    A merged input is used as-is. For a master, an existing library sibling is reused;
    otherwise the mix is regenerated into `workdir` (a temp intermediate to clean up).
    """
    if media.is_merged(src):
        return src, False
    sibling = library / media.merged_name_for(src)
    if sibling.exists():
        return sibling, False
    out = workdir / media.merged_name_for(src)
    print(f"  merging audio tracks -> {out.name}")
    media.regenerate_merged(src, out)
    return out, True


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
    subprocess.run(
        ["wl-copy", "--type", "text/uri-list"],
        input=(uri + "\r\n").encode(),  # text/uri-list wants CRLF-terminated URIs
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
    ap.add_argument("clip", nargs="?", help='a path, a stem/substring, or "latest"; omit to pick interactively')
    ap.add_argument("--pick", action="store_true", help="force the interactive picker even if a clip is given")
    ap.add_argument("--out-dir", type=Path, default=_default_out_dir(cfg.library_dir),
                    help="where to write the compressed file (default: the library, or CLIP_SHARE_DIR)")
    ap.add_argument("--library", type=Path, default=cfg.library_dir)
    ap.add_argument("--cap-bytes", type=int, default=DISCORD_UNBOOSTED_CAP)
    ap.add_argument("--no-clipboard", action="store_true", help="compress only, don't touch the clipboard")
    # Dolphin is off by default (clipboard is the happy path); --reveal opts into it,
    # --no-reveal is the explicit off-switch.
    ap.add_argument("--reveal", action=argparse.BooleanOptionalAction, default=False,
                    help="open the folder in the file manager for drag-drop (default: no)")
    args = ap.parse_args()

    if args.pick or args.clip is None:
        src = pick_master(args.library)
    else:
        src = resolve_clip(args.clip, args.library)

    # Feasibility BEFORE the (possibly expensive) merge: a clip too long to fit the cap
    # at usable quality should fail fast, not after mixing a multi-hundred-MB rendition.
    dur = media.probe_duration(src)
    if dur is None:
        sys.exit(f"could not probe duration of {src}")
    if video_budget_kbps(dur, args.cap_bytes, _HEADROOM, _AUDIO_KBPS) < _MIN_VIDEO_KBPS:
        sys.exit(
            f"{src.name}: {dur:.0f}s is too long to fit {_fmt_mib(args.cap_bytes)} at usable "
            f"quality. Trim it, or share to a boosted server (--cap-bytes)."
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    # <stem>_merged_<cap>mb.mp4; overwrites a prior rendition of the same clip + cap.
    dst = args.out_dir / _share_name(media.stem_of(src), args.cap_bytes)

    # Any on-demand merge goes to a system tempdir (auto-cleaned), never the library.
    with tempfile.TemporaryDirectory(prefix="clip-merge_") as td:
        merged, _is_temp = ensure_merged(src, args.library, Path(td))
        print(f"compressing {merged.name} -> {dst}")
        result = compress_for_share(merged, dst, cap_bytes=args.cap_bytes)
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
