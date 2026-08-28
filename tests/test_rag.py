"""Tests for grounded answer synthesis (clip_core.rag).

Retrieval is real (a small in-memory vec_clips, as in test_embed), but generation is stubbed
with a fake runner -- the same `_FakeRunner` idiom as test_classify -- so no `claude` CLI call
is made and no budget is spent. Skipped entirely if the embedding deps aren't installed.
"""
import pytest

pytest.importorskip("sentence_transformers")
pytest.importorskip("sqlite_vec")

from clip_core import embed, index, rag  # noqa: E402
from clip_core.schema import connect  # noqa: E402


class _FakeRunner:
    """Stand-in for the `claude` CLI: records the call kwargs, returns a fixed payload."""

    def __init__(self, payload):
        self._payload = payload
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self._payload


def _clip(stem, description, tags, game="test game"):
    return index.Clip(stem=stem, master_path=f"/lib/{stem}.mp4", game=game,
                       description=description, tags=tags)


def _seed(conn):
    embed.ensure_vec_table(conn)
    for c in [
        _clip("clutch1", "1v4 retake, insane comeback to win the round", ["clutch", "ace"]),
        _clip("recipe1", "how to bake sourdough bread at home", ["cooking"]),
        _clip("scenery1", "a calm timelapse of clouds over the mountains", ["nature"]),
    ]:
        index.upsert_clip(conn, c)
        embed.index_clip(conn, c)


def test_build_answer_schema_pins_citations_to_retrieved_stems():
    schema = rag.build_answer_schema(["a", "b"])
    assert schema["properties"]["clip_ids"]["items"]["enum"] == ["a", "b"]
    assert schema["required"] == ["answer", "clip_ids"]
    assert schema["additionalProperties"] is False


def test_ask_assembles_grounded_context_and_returns_answer():
    conn = connect(":memory:")
    _seed(conn)
    runner = _FakeRunner({"answer": "The clutch clip is clutch1.", "clip_ids": ["clutch1"]})

    answer, candidates = rag.ask(conn, "that crazy clutch play", 3, model="claude-test", runner=runner)

    # returned the model's grounded answer + citation
    assert answer.answer == "The clutch clip is clutch1."
    assert answer.clip_ids == ["clutch1"]
    # retrieval was real: the top candidate is the clutch clip, not the recipe/timelapse
    assert candidates[0].stem == "clutch1"
    # the runner saw the retrieved clips as context, the grounding system prompt, the
    # citation-constrained schema, and the resolved model
    assert "clutch1" in runner.kwargs["prompt"]
    assert "1v4 retake" in runner.kwargs["prompt"]
    assert "ONLY these candidates" in runner.kwargs["system"]
    assert set(runner.kwargs["schema"]["properties"]["clip_ids"]["items"]["enum"]) == {
        "clutch1", "recipe1", "scenery1"
    }
    assert runner.kwargs["model"] == "claude-test"


def test_ask_respects_k_in_candidate_set():
    conn = connect(":memory:")
    _seed(conn)
    runner = _FakeRunner({"answer": "x", "clip_ids": []})
    _, candidates = rag.ask(conn, "anything", 1, runner=runner)
    assert len(candidates) == 1
    assert len(runner.kwargs["schema"]["properties"]["clip_ids"]["items"]["enum"]) == 1


def test_ask_short_circuits_when_nothing_retrieved():
    """Empty corpus -> a 'nothing matched' answer and NO CLI call."""
    conn = connect(":memory:")
    embed.ensure_vec_table(conn)  # table exists but has no vectors
    runner = _FakeRunner({"answer": "should not be used", "clip_ids": []})

    answer, candidates = rag.ask(conn, "anything at all", 5, runner=runner)

    assert candidates == []
    assert answer.clip_ids == []
    assert "No matching clips" in answer.answer
    assert runner.kwargs is None  # runner was never invoked -> no budget spent
