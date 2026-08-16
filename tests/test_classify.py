from clip_core.classify import build_batch_schema, build_schema, llm_classify, llm_classify_batch
from clip_core.tags import TagVocab


class _FakeRunner:
    """Stand-in for the `claude` CLI: records the call kwargs, returns a fixed payload."""

    def __init__(self, payload):
        self._payload = payload
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self._payload


class _RecordingRunner:
    """Records every call and returns the next queued payload (one per chunk)."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self._payloads.pop(0)


def test_maps_description_to_vocab():
    vocab = TagVocab(["clutch", "fail", "ace"])
    runner = _FakeRunner({"tags": ["clutch", "ace"], "proposed_tag": None})
    result = llm_classify("1v4 retake for the round", vocab, runner=runner)
    assert result.tags == ["clutch", "ace"]
    assert result.proposed_tag is None


def test_proposes_new_tag_when_nothing_fits():
    vocab = TagVocab(["clutch"])
    runner = _FakeRunner({"tags": [], "proposed_tag": "pentakill"})
    result = llm_classify("a wild new thing", vocab, runner=runner)
    assert result.tags == []
    assert result.proposed_tag == "pentakill"


def test_schema_enum_reflects_vocab():
    vocab = TagVocab(["clutch", "fail", "ace"])
    schema = build_schema(vocab)
    assert schema["properties"]["tags"]["items"]["enum"] == ["clutch", "fail", "ace"]
    assert schema["additionalProperties"] is False


def test_passes_model_and_constrained_schema():
    vocab = TagVocab(["clutch"])
    runner = _FakeRunner({"tags": ["clutch"], "proposed_tag": None})
    llm_classify("x", vocab, runner=runner, model="claude-test")
    assert runner.kwargs["model"] == "claude-test"
    assert runner.kwargs["schema"]["properties"]["tags"]["items"]["enum"] == ["clutch"]
    assert runner.kwargs["prompt"] == "Description: x"


def test_batch_schema_enum_reflects_vocab():
    vocab = TagVocab(["clutch", "ace"])
    item = build_batch_schema(vocab)["properties"]["results"]["items"]
    assert item["properties"]["tags"]["items"]["enum"] == ["clutch", "ace"]
    assert item["properties"]["id"]["type"] == "string"


def test_batch_maps_results_by_id():
    vocab = TagVocab(["clutch", "fail", "ace"])
    runner = _FakeRunner({"results": [
        {"id": "a", "tags": ["clutch"], "proposed_tag": None},
        {"id": "b", "tags": ["fail", "ace"], "proposed_tag": "meltdown"},
    ]})
    out = llm_classify_batch([("a", "1v4 retake"), ("b", "threw the game")], vocab, runner=runner)
    assert out["a"].tags == ["clutch"]
    assert out["b"].tags == ["fail", "ace"]
    assert out["b"].proposed_tag == "meltdown"
    # every id is a single prompt line
    assert runner.kwargs["prompt"] == "[a] 1v4 retake\n[b] threw the game"


def test_batch_missing_id_defaults_empty():
    vocab = TagVocab(["clutch"])
    runner = _FakeRunner({"results": [{"id": "a", "tags": ["clutch"], "proposed_tag": None}]})
    out = llm_classify_batch([("a", "x"), ("b", "y")], vocab, runner=runner)
    assert out["a"].tags == ["clutch"]
    assert out["b"].tags == []  # model omitted b -> empty classification
    assert out["b"].proposed_tag is None


def test_batch_chunks_and_sends_vocab_once_per_chunk():
    vocab = TagVocab(["clutch"])
    runner = _RecordingRunner([
        {"results": [{"id": "a", "tags": ["clutch"], "proposed_tag": None},
                     {"id": "b", "tags": [], "proposed_tag": None}]},
        {"results": [{"id": "c", "tags": ["clutch"], "proposed_tag": None}]},
    ])
    items = [("a", "1"), ("b", "2"), ("c", "3")]
    out = llm_classify_batch(items, vocab, runner=runner, chunk_size=2)
    assert set(out) == {"a", "b", "c"}
    assert len(runner.calls) == 2  # two chunks
    assert runner.calls[0]["schema"]["required"] == ["results"]
