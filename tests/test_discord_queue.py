import json

from clip_core import discord_queue as dq


def test_enqueue_writes_atomic_json(tmp_path):
    job = dq.enqueue(tmp_path, "/srv/dev/clips/library/the goblin combo_merged_10mb.mp4",
                     message="clutch 1v3", cap_mb=10)
    # lands in incoming/, no leftover temp files
    assert job.parent == tmp_path / "incoming"
    assert job.suffix == ".json"
    assert list((tmp_path / "incoming").glob(".job_*.tmp")) == []

    data = json.loads(job.read_text())
    assert data["file"].endswith("the goblin combo_merged_10mb.mp4")
    assert data["message"] == "clutch 1v3"
    assert data["cap_mb"] == 10
    assert data["created"]  # timestamp present


def test_enqueue_defaults_message_none_and_makes_dirs(tmp_path):
    q = tmp_path / "discord-queue"
    job = dq.enqueue(q, "/x/clip_merged_10mb.mp4")
    assert json.loads(job.read_text())["message"] is None
    for sub in (dq.INCOMING, dq.SENT, dq.FAILED):
        assert (q / sub).is_dir()


def test_enqueue_unique_names(tmp_path):
    a = dq.enqueue(tmp_path, "/x/a_merged_10mb.mp4")
    b = dq.enqueue(tmp_path, "/x/a_merged_10mb.mp4")
    assert a != b  # microsecond timestamp keeps two posts of the same clip distinct
