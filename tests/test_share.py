"""share.py helpers: the share-rendition naming/classification that keeps our own
compressed outputs from masquerading as source masters in the picker."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "clip-distributor"))

import share  # noqa: E402


def test_share_name_strips_and_retags():
    assert share._share_name("the goblin combo", 10 * 1024 * 1024) == "the goblin combo_merged_10mb.mp4"


def test_share_name_reflects_cap():
    assert share._share_name("foo", 50 * 1024 * 1024) == "foo_merged_50mb.mp4"


def test_is_share_rendition():
    assert share.is_share_rendition("foo_merged_10mb.mp4")
    assert share.is_share_rendition("foo_merged_50mb")
    assert not share.is_share_rendition("foo_merged.mp4")
    assert not share.is_share_rendition("foo.mp4")


def test_picker_excludes_our_renditions(tmp_path):
    (tmp_path / "clipA.mp4").touch()                 # master -> listed
    (tmp_path / "clipA_merged.mp4").touch()          # merged rendition -> excluded
    (tmp_path / "clipA_merged_10mb.mp4").touch()     # our share output -> excluded
    names = [p.name for p in share._masters_newest_first(tmp_path)]
    assert names == ["clipA.mp4"]
