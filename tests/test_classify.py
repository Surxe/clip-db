from clip_core.classify import build_schema, llm_classify
from clip_core.tags import TagVocab


class _FakeRunner:
    """Stand-in for the `claude` CLI: records the call kwargs, returns a fixed payload."""

    def __init__(self, payload):
        self._payload = payload
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self._payload


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
