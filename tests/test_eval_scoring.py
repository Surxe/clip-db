"""Offline unit test for the eval scorer -- no CLI, provable metric math.

Two cases over two runs with hand-computed truth: run 0 is perfect, run 1 drops a
tag, adds a wrong one, and emits a spurious proposed_tag. Every metric below is
worked out by hand from that fixture.
"""
from clip_core.classify import Classification
from evals.run_eval import Case, score


def _cases():
    return [
        Case(id="A", description="", expected={"x", "y"}),
        Case(id="B", description="", expected={"z"}),
    ]


def _per_run():
    return [
        {"A": Classification(["x", "y"]), "B": Classification(["z"])},            # perfect run
        {"A": Classification(["x", "w"]), "B": Classification(["z"], "q")},        # miss y, extra w, proposal q
    ]


def test_micro_and_exact_and_proposed():
    m = score(_cases(), _per_run())
    # tp=5, fp=1, fn=1 -> P=R=F1=5/6
    assert m["micro_precision"] == 0.8333
    assert m["micro_recall"] == 0.8333
    assert m["micro_f1"] == 0.8333
    # 3 of 4 (case, run) trials are exact; 1 of 4 carries a proposed_tag
    assert m["exact_match_rate"] == 0.75
    assert m["proposed_tag_fp_rate"] == 0.25


def test_macro_and_variance_and_stability():
    m = score(_cases(), _per_run())
    # per-tag F1: x=1.0, y=0.6667, z=1.0, w=0.0 -> mean 0.6667
    assert m["macro_f1"] == 0.6667
    # run 0 micro-F1 = 1.0, run 1 = 0.6667
    assert m["per_run_micro_f1"] == [1.0, 0.6667]
    assert m["mean_micro_f1"] == 0.8333
    assert m["min_micro_f1"] == 0.6667
    assert m["max_micro_f1"] == 1.0
    # B identical across runs, A differs -> 1 of 2 stable
    assert m["case_stability_rate"] == 0.5


def test_per_tag_table():
    m = score(_cases(), _per_run())
    assert m["per_tag"]["x"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 2}
    assert m["per_tag"]["y"]["support"] == 2  # expected in both runs
    assert m["per_tag"]["y"]["recall"] == 0.5
    assert m["per_tag"]["w"]["precision"] == 0.0  # only ever a false positive
