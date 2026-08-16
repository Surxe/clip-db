#!/usr/bin/env python3
"""Turnkey refresh of the War Robots Frontiers tag block in tags.json.

Rerun this after a WRF game update to pull the latest source data, regenerate the
game's weapon/module/ability tags, and see exactly which tags appeared or vanished.

Chain:
  1. git pull the WRFrontiersDB-Data repo so current/Objects is fresh   (--no-pull to skip)
  2. snapshot tags.json, then run scripts/extract_wrf_tags.py --merge    (single source of truth)
  3. print the per-group delta -- tags added / removed since last run
  4. run pytest so a broken vocab is caught immediately                 (--no-tests to skip)

Usage:
    python scripts/refresh_wrf_tags.py [--no-pull] [--no-tests] [OBJECTS_DIR]

OBJECTS_DIR defaults the same way extract_wrf_tags.py does (env WRF_OBJECTS_DIR or the
sibling WRFrontiersDB-Data 'current/Objects' path).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACTOR = REPO_ROOT / "scripts" / "extract_wrf_tags.py"
TAGS_JSON = REPO_ROOT / "tags.json"
GAME_NAME = "War Robots Frontiers"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import extract_wrf_tags  # noqa: E402  -- reuse DEFAULT_OBJECTS


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, **kw)


def _game_groups(tags_path: Path) -> dict[str, list[str]]:
    """Read tags.json -> {group: [tags]} for the WRF block (empty if absent)."""
    if not tags_path.exists():
        return {}
    data = json.loads(tags_path.read_text())
    return data.get("games", {}).get(GAME_NAME, {}).get("groups", {})


def _data_repo_toplevel(objects_dir: Path) -> Path | None:
    r = subprocess.run(
        ["git", "-C", str(objects_dir), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def _current_branch(repo: Path) -> str | None:
    r = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    )
    branch = r.stdout.strip()
    return branch if r.returncode == 0 and branch and branch != "HEAD" else None


def _remote_has_branch(repo: Path, branch: str) -> bool:
    """True if origin actually has this branch right now (ignores stale tracking refs)."""
    r = subprocess.run(
        ["git", "-C", str(repo), "ls-remote", "--heads", "origin", branch],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and bool(r.stdout.strip())


def _report_delta(before: dict, after: dict) -> None:
    groups = sorted(set(before) | set(after))
    total_added = total_removed = 0
    for g in groups:
        b, a = set(before.get(g, [])), set(after.get(g, []))
        added, removed = sorted(a - b), sorted(b - a)
        total_added += len(added)
        total_removed += len(removed)
        if added or removed:
            print(f"\n  {g}  (+{len(added)} / -{len(removed)})")
            for t in added:
                print(f"    + {t}")
            for t in removed:
                print(f"    - {t}")
    print()
    if total_added or total_removed:
        print(f"Delta: +{total_added} added, -{total_removed} removed across {len(groups)} groups.")
    else:
        print("Delta: none -- tags.json was already in sync with the source data.")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("objects_dir", nargs="?", default=extract_wrf_tags.DEFAULT_OBJECTS,
                    help=f"WRFrontiersDB-Data Objects dir (default: {extract_wrf_tags.DEFAULT_OBJECTS})")
    ap.add_argument("--no-pull", action="store_true",
                    help="Skip git-pulling WRFrontiersDB-Data; extract from what is checked out.")
    ap.add_argument("--no-tests", action="store_true",
                    help="Skip the pytest run after merging.")
    args = ap.parse_args()

    objects_dir = Path(args.objects_dir)

    # 1. refresh source data
    if not args.no_pull:
        repo = _data_repo_toplevel(objects_dir)
        if repo is None:
            print(f"error: {objects_dir} is not inside a git repo; use --no-pull to extract in place.")
            return 1
        branch = _current_branch(repo)
        if branch is None:
            print("error: data repo has a detached HEAD; check out a branch or use --no-pull.")
            return 1
        print(f"== Pulling source data: {repo} (branch {branch})")
        if _remote_has_branch(repo, branch):
            # Pull whatever branch is checked out, straight from origin -- this bypasses any
            # stale branch.<name>.merge config so a non-main/non-dev branch still updates.
            r = _run(["git", "-C", str(repo), "pull", "--ff-only", "origin", branch])
            if r.returncode != 0:
                print("error: git pull failed. Resolve the data repo state, or rerun with --no-pull.")
                return 1
        else:
            # Active branch has no live counterpart on origin (e.g. a local-only or
            # deleted-upstream branch) -- nothing to pull; use the checked-out data as-is.
            print(f"note: origin has no '{branch}' branch; nothing to pull, "
                  f"extracting from the checked-out data as-is.")
    else:
        print("== Skipping source-data pull (--no-pull)")

    # 2. snapshot + regenerate via the existing extractor (one source of truth)
    before = _game_groups(TAGS_JSON)
    print(f"\n== Regenerating {GAME_NAME} block in {TAGS_JSON.name}")
    r = _run([sys.executable, str(EXTRACTOR), str(objects_dir), "--merge", str(TAGS_JSON)])
    if r.returncode != 0:
        print("error: extraction failed; tags.json left unchanged.")
        return 1
    after = _game_groups(TAGS_JSON)

    # 3. delta
    print("\n== Tag delta")
    _report_delta(before, after)

    # 4. verify
    if not args.no_tests:
        print("\n== Running tests")
        r = _run([sys.executable, "-m", "pytest", str(REPO_ROOT)])
        if r.returncode != 0:
            print("error: pytest failed after merge -- inspect the new vocab before committing.")
            return 1

    print("\nDone. Review the tags.json diff and commit when it looks right.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
