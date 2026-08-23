"""The dev -> ethan handoff for Discord webhook posting (spool queue).

The MCP runs as `dev` and cannot post to Discord itself: the webhook URL is an
ethan-owned secret (chmod 600) that dev can't read, and dev -> ethan sudo isn't
granted. So dev does the media prep it IS allowed to do (merge + compress on the
dev-owned library) and drops a small job file here; an ethan-side systemd watcher
consumes the queue and runs `clip-post`, which reads the secret as ethan and does
the upload. The secret never touches dev.

Layout under the queue dir (default /srv/dev/clips/discord-queue, group-writable
setgid so both users can drop/move files):

    incoming/   jobs waiting for the watcher   (dev writes here)
    sent/       jobs the watcher posted OK      (watcher moves here)
    failed/     jobs the watcher couldn't post  (watcher moves here)

A job is JSON: {"file": <abs path to an upload-ready rendition>, "message": <str|null>,
"cap_mb": <int>, "created": <iso8601>}. Jobs are written atomically (temp + rename)
so the watcher never reads a half-written file.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

INCOMING = "incoming"
SENT = "sent"
FAILED = "failed"


def incoming_dir(queue_dir) -> Path:
    return Path(queue_dir) / INCOMING


def ensure_dirs(queue_dir) -> None:
    """Create the queue subdirs (setgid, group-writable) if missing, so dev writes and
    the ethan watcher moves within them. Best-effort on the mode bits."""
    for name in (INCOMING, SENT, FAILED):
        d = Path(queue_dir) / name
        d.mkdir(parents=True, exist_ok=True)
        try:
            d.chmod(0o2775)
        except OSError:
            pass  # not the owner (e.g. dir pre-created by install); leave perms as-is


def _job_name(file_path: Path) -> str:
    # Sort-friendly, collision-resistant: microsecond timestamp + the rendition stem.
    ts = datetime.now().strftime("%Y%m%dT%H%M%S_%f")
    return f"{ts}_{file_path.stem}.json"


def enqueue(queue_dir, file_path, message: str | None = None, cap_mb: int = 10) -> Path:
    """Drop a post job into incoming/ and return its path. Writes atomically.

    `file_path` should already be upload-ready (merged + under the cap). The message is
    optional; the watcher falls back to the clip's name when it's None.
    """
    file_path = Path(file_path)
    ensure_dirs(queue_dir)
    dst = incoming_dir(queue_dir) / _job_name(file_path)
    payload = {
        "file": str(file_path),
        "message": message,
        "cap_mb": cap_mb,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    # temp file in the same dir so the rename is atomic (same filesystem).
    fd, tmp = tempfile.mkstemp(prefix=".job_", suffix=".tmp", dir=str(incoming_dir(queue_dir)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        # mkstemp is 0600; the ethan watcher must READ the job, so make it group-readable.
        os.chmod(tmp, 0o640)
        os.replace(tmp, dst)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return dst
