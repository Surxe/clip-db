import json
from types import SimpleNamespace

from clip_core.classify import build_schema, llm_classify
from clip_core.tags import TagVocab


class _FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        text = json.dumps(self._payload)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


class _FakeClient:
    def __init__(self, payload):
        self.messages = _FakeMessages(payload)


def test_maps_description_to_vocab():
    vocab = TagVocab(["clutch", "fail", "ace"])
    client = _FakeClient({"tags": ["clutch", "ace"], "proposed_tag": None})
    result = llm_classify("1v4 retake for the round", vocab, client=client)
    assert result.tags == ["clutch", "ace"]
    assert result.proposed_tag is None


def test_proposes_new_tag_when_nothing_fits():
    vocab = TagVocab(["clutch"])
    client = _FakeClient({"tags": [], "proposed_tag": "pentakill"})
    result = llm_classify("a wild new thing", vocab, client=client)
    assert result.tags == []
    assert result.proposed_tag == "pentakill"


def test_schema_enum_reflects_vocab():
    vocab = TagVocab(["clutch", "fail", "ace"])
    schema = build_schema(vocab)
    assert schema["properties"]["tags"]["items"]["enum"] == ["clutch", "fail", "ace"]
    assert schema["additionalProperties"] is False


def test_passes_model_and_constrained_format():
    vocab = TagVocab(["clutch"])
    client = _FakeClient({"tags": ["clutch"], "proposed_tag": None})
    llm_classify("x", vocab, client=client, model="claude-test")
    assert client.messages.kwargs["model"] == "claude-test"
    assert client.messages.kwargs["output_config"]["format"]["type"] == "json_schema"
