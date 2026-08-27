#!/usr/bin/env python3
"""Evaluate the tag classifier against a hand-labeled golden set.

Mirrors the real pipeline (clip-tagger/ingest.py): same vocab, relations, and model,
routed through `llm_classify_batch`. Each run is one batched `claude` CLI call over
all cases, so the whole eval costs `--runs` calls -- and every call is cached, so a
re-score is free. Because the classifier is nondeterministic, each case is run N
times and the per-run F1 spread is reported.

  # First real collect + store a baseline (spends CLI budget: --runs calls)
  python evals/run_eval.py --runs 5 --write-baseline

  # Re-score from cache only, zero CLI calls (proves budget isolation)
  python evals/run_eval.py --runs 5 --offline

  # Regression gate: fail (exit 1) if micro-F1 dropped below the baseline
  python evals/run_eval.py --runs 5 --gate

  # Discard the cache and re-collect fresh samples
  python evals/run_eval.py --runs 5 --refresh

Caching keys on (model, run_index, prompt, system, schema): the run index is part
of the key so the N runs stay distinct -- collapsing them would erase the very
nondeterminism we set out to measure. There is no temperature control in the
`claude` CLI, so the observed variance is whatever the CLI defaults produce.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

from clip_core.classify import _claude_cli_runner, llm_classify_batch
from clip_core.config import load_config
from clip_core.relations import TagRelations
from clip_core.tags import load_vocab, normalize

EVALS_DIR = Path(__file__).resolve().parent
GOLDEN_PATH = EVALS_DIR / "golden.jsonl"
BASELINE_PATH = EVALS_DIR / "baseline.json"
CACHE_DIR = EVALS_DIR / ".cache"
GATE_METRIC = "micro_f1"


@dataclass
class Case:
    id: str
    description: str
    expected: set[str]
    game: str = ""


class CachingRunner:
    """Wraps the real `claude` CLI runner with a per-run on-disk cache.

    The runner contract is `runner(*, prompt, system, schema, model) -> dict`. We key
    the cache on that call plus `run_index`, so identical batch prompts across runs do
    not collapse onto one cached answer.
    """

    def __init__(self, *, run_index, cache_dir, inner, offline=False, refresh=False):
        self.run_index = run_index
        self.cache_dir = Path(cache_dir)
        self.inner = inner
        self.offline = offline
        self.refresh = refresh

    def _key(self, *, prompt, system, schema, model) -> str:
        blob = "\x00".join(
            [model, str(self.run_index), prompt, system, json.dumps(schema, sort_keys=True)]
        )
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()

    def __call__(self, *, prompt, system, schema, model) -> dict:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{self._key(prompt=prompt, system=system, schema=schema, model=model)}.json"
        if path.exists() and not self.refresh:
            return json.loads(path.read_text())
        if self.offline:
            raise SystemExit(
                f"cache miss in --offline mode (run {self.run_index}); run a real collect first"
            )
        result = self.inner(prompt=prompt, system=system, schema=schema, model=model)
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        return result


def load_golden(path: Path) -> list[Case]:
    cases: list[Case] = []
    for i, line in enumerate(path.read_text().splitlines()):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        cases.append(
            Case(
                id=obj.get("id") or f"c{i:02d}",
                description=obj["description"],
                expected={normalize(t) for t in obj["expected_tags"]},
                game=obj.get("game", ""),
            )
        )
    return cases


def collect(cases, vocab, relations, model, *, n_runs, offline, refresh):
    """Run the classifier `n_runs` times over the golden set. Returns list[dict[id -> Classification]]."""
    items = [(c.id, c.description) for c in cases]
    per_run = []
    for run in range(n_runs):
        runner = CachingRunner(
            run_index=run, cache_dir=CACHE_DIR, inner=_claude_cli_runner, offline=offline, refresh=refresh
        )
        per_run.append(llm_classify_batch(items, vocab, relations=relations, model=model, runner=runner))
    return per_run


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def score(cases: list[Case], per_run) -> dict:
    """Compute micro/macro/exact-match/proposed-FP metrics + per-run variance.

    `per_run` is a list (one per run) of dict[id -> Classification]; each Classification
    exposes `.tags` (the resolved predicted list) and `.proposed_tag`. Scoring is a pure
    function of the golden expectations and these predictions -- no CLI calls.
    """
    n_runs = len(per_run)
    tp = fp = fn = 0
    exact_hits = proposed_fp = trials = 0
    per_tag: dict[str, list[int]] = {}  # tag -> [tp, fp, fn]
    per_run_micro: list[float] = []
    predictions: dict[str, list[frozenset]] = {c.id: [] for c in cases}

    for run in per_run:
        r_tp = r_fp = r_fn = 0
        for c in cases:
            pred = run.get(c.id)
            predicted = {normalize(t) for t in (pred.tags if pred else [])}
            predictions[c.id].append(frozenset(predicted))
            expected = c.expected
            trials += 1
            if predicted == expected:
                exact_hits += 1
            if pred is not None and pred.proposed_tag:
                proposed_fp += 1  # every golden case is satisfiable, so any proposal is a false positive
            for tag in predicted | expected:
                slot = per_tag.setdefault(tag, [0, 0, 0])
                if tag in predicted and tag in expected:
                    tp += 1; r_tp += 1; slot[0] += 1
                elif tag in predicted:
                    fp += 1; r_fp += 1; slot[1] += 1
                else:
                    fn += 1; r_fn += 1; slot[2] += 1
        per_run_micro.append(_prf(r_tp, r_fp, r_fn)[2])

    micro_p, micro_r, micro_f1 = _prf(tp, fp, fn)
    tag_f1 = {t: _prf(*c) for t, c in per_tag.items()}
    macro_f1 = statistics.fmean(f for _, _, f in tag_f1.values()) if tag_f1 else 0.0
    stable = sum(1 for preds in predictions.values() if len(set(preds)) == 1)

    return {
        "n_runs": n_runs,
        "n_cases": len(cases),
        "micro_precision": round(micro_p, 4),
        "micro_recall": round(micro_r, 4),
        "micro_f1": round(micro_f1, 4),
        "macro_f1": round(macro_f1, 4),
        "exact_match_rate": round(exact_hits / trials, 4) if trials else 0.0,
        "proposed_tag_fp_rate": round(proposed_fp / trials, 4) if trials else 0.0,
        "per_run_micro_f1": [round(x, 4) for x in per_run_micro],
        "mean_micro_f1": round(statistics.fmean(per_run_micro), 4) if per_run_micro else 0.0,
        "stdev_micro_f1": round(statistics.pstdev(per_run_micro), 4) if len(per_run_micro) > 1 else 0.0,
        "min_micro_f1": round(min(per_run_micro), 4) if per_run_micro else 0.0,
        "max_micro_f1": round(max(per_run_micro), 4) if per_run_micro else 0.0,
        "case_stability_rate": round(stable / len(cases), 4) if cases else 0.0,
        "per_tag": {
            t: {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4),
                "support": per_tag[t][0] + per_tag[t][2]}
            for t, (p, r, f) in sorted(tag_f1.items())
        },
    }


def print_report(m: dict, model: str) -> None:
    print(f"\nClassifier eval  |  model={model}  runs={m['n_runs']}  cases={m['n_cases']}")
    print("-" * 60)
    print(f"micro   P={m['micro_precision']:.3f}  R={m['micro_recall']:.3f}  F1={m['micro_f1']:.3f}   <- gate metric")
    print(f"macro   F1={m['macro_f1']:.3f}")
    print(f"exact-match rate      {m['exact_match_rate']:.3f}")
    print(f"proposed_tag FP rate  {m['proposed_tag_fp_rate']:.3f}")
    print(
        f"micro-F1 across runs  mean={m['mean_micro_f1']:.3f}  stdev={m['stdev_micro_f1']:.3f}  "
        f"min={m['min_micro_f1']:.3f}  max={m['max_micro_f1']:.3f}  {m['per_run_micro_f1']}"
    )
    print(f"per-case tag stability {m['case_stability_rate']:.3f} (fraction identical across all runs)")
    print("\nper-tag (support = times the tag was expected)")
    print(f"  {'tag':<28}{'P':>6}{'R':>6}{'F1':>6}{'sup':>6}")
    for tag, s in m["per_tag"].items():
        print(f"  {tag:<28}{s['precision']:>6.2f}{s['recall']:>6.2f}{s['f1']:>6.2f}{s['support']:>6}")
    print()


def write_baseline(m: dict, model: str) -> None:
    baseline = {
        "model": model,
        "n_runs": m["n_runs"],
        "generated_at": date.today().isoformat(),
        "golden_set": GOLDEN_PATH.name,
        "n_cases": m["n_cases"],
        "gate_metric": GATE_METRIC,
        "micro_f1": m["micro_f1"],
        "macro_f1": m["macro_f1"],
        "exact_match_rate": m["exact_match_rate"],
        "proposed_tag_fp_rate": m["proposed_tag_fp_rate"],
    }
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote baseline -> {BASELINE_PATH} ({GATE_METRIC}={m['micro_f1']:.4f})")


def check_gate(m: dict, epsilon: float) -> int:
    if not BASELINE_PATH.exists():
        print(f"--gate: no baseline at {BASELINE_PATH}; run --write-baseline first", file=sys.stderr)
        return 1
    baseline = json.loads(BASELINE_PATH.read_text())
    floor = baseline[GATE_METRIC] - epsilon
    current = m[GATE_METRIC]
    if current < floor:
        print(f"GATE FAIL: {GATE_METRIC} {current:.4f} < baseline {baseline[GATE_METRIC]:.4f} - {epsilon} = {floor:.4f}",
              file=sys.stderr)
        return 1
    print(f"gate ok: {GATE_METRIC} {current:.4f} >= floor {floor:.4f} (baseline {baseline[GATE_METRIC]:.4f})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=5, help="times to classify each case (default 5)")
    ap.add_argument("--gate", action="store_true", help="exit non-zero if micro-F1 dropped below baseline")
    ap.add_argument("--gate-epsilon", type=float, default=0.05, help="tolerance below baseline before failing (default 0.05)")
    ap.add_argument("--write-baseline", action="store_true", help="write baseline.json from this run")
    ap.add_argument("--refresh", action="store_true", help="ignore cache and re-collect (spends CLI budget)")
    ap.add_argument("--offline", action="store_true", help="never call the CLI; error on any cache miss")
    args = ap.parse_args()

    cfg = load_config()
    vocab = load_vocab(cfg.tags_path)
    relations = TagRelations.load(cfg.aliases_path, cfg.implications_path)
    cases = load_golden(GOLDEN_PATH)

    per_run = collect(
        cases, vocab, relations, cfg.model,
        n_runs=args.runs, offline=args.offline, refresh=args.refresh,
    )
    metrics = score(cases, per_run)
    print_report(metrics, cfg.model)

    if args.write_baseline:
        write_baseline(metrics, cfg.model)
    if args.gate:
        return check_gate(metrics, args.gate_epsilon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
