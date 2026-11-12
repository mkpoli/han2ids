"""Create a compact publication report from selective scores.

Run ``python -m benchmark.summarize_selective --score SCORES.json --output
SUMMARY.json``. The source report and external source data remain separate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PROVENANCE_FIELDS = ("inputs_sha256", "references_sha256", "scorer_sha256",
                     "expansion_scorer_sha256", "expansion_sha256", "score_helpers_sha256",
                     "evaluator_sha256", "index_sha256", "source_specs", "run_manifest_sha256",
                     "prediction_sha256", "python_version", "unicode_version", "evaluator_unicode_version")
SAMPLE_FIELDS = ("sample_id", "review_status", "prediction_run_status", "candidate_count",
                 "prediction_status", "reference_eligible", "reference_statuses", "expansion_status",
                 "selective_status", "selective_states_visited", "selective_recall_at_5_candidate_count",
                 "selective_recall_at_5_matched_rank")


def _numeric_tree(value):
    """Copy numeric aggregate structures, rejecting unexpected text or payloads."""
    if value is None or type(value) in (bool, int, float):
        return value
    if isinstance(value, list):
        return [_numeric_tree(item) for item in value]
    if isinstance(value, dict):
        return {key: _numeric_tree(item) for key, item in value.items()}
    raise ValueError("expected numeric scores")


def _aggregate(data):
    fields = ("sample_count", "character_count", "reference_eligible_samples", "selective_status_counts",
              "selective_states_visited", "indeterminate_after_baseline", "scores", "per_font")
    return {key: _numeric_tree(data[key]) for key in fields}


def _policy(policy):
    if policy is None:
        return None
    document = policy["document"]
    rules = [{key: rule[key] for key in ("components", "positions", "contexts") if key in rule}
             for rule in document["rules"]]
    return {"sha256": policy["sha256"], "document": {"policy": document["policy"], "rules": rules}}


def _sources(sources):
    collisions = sources["single_definition_collisions"]
    collision_fields = ("class_count", "character_count", "example_limit", "characters_per_example_limit",
                        "scope", "interpretation")
    return {"mode": sources["mode"],
            "sources": [{key: source[key] for key in ("path", "sha256", "provenance", "license")}
                        for source in sources["sources"]],
            "counts": _numeric_tree(sources["counts"]),
            "single_definition_collisions": {key: collisions[key] for key in collision_fields if key in collisions}}


def _paired(pairs):
    output = {}
    for name, pair in pairs.items():
        if pair["cluster"] != "char" or pair["coverage"] != "fixed reference eligibility":
            raise ValueError("unexpected bootstrap configuration")
        output[name] = {"cluster": "char", "coverage": "fixed reference eligibility",
                        "iterations": _numeric_tree(pair["iterations"]), "seed": _numeric_tree(pair["seed"]),
                        "scores": {metric: _numeric_tree(pair["scores"][metric]) for metric in
                                   ("eligible_selective_hit", "eligible_selective_upper",
                                    "eligible_selective_recall_at_5", "eligible_selective_recall_at_5_upper")},
                        "interpretation": "Intervals describe paired differences in the reported lower and upper bounds, not confidence intervals for true accuracy."}
    return output


def summarize(report, source_sha256):
    """Project an ids-selective-scores-v1 report without comparisons or source IDS."""
    if not isinstance(report, dict) or report.get("format") != "ids-selective-scores-v1":
        raise ValueError("expected ids-selective-scores-v1 report")
    provenance = report["provenance"]
    runs = report["runs"]
    prediction_hashes = provenance["prediction_sha256"]
    if not isinstance(runs, dict) or not runs or not isinstance(prediction_hashes, dict) or runs.keys() != prediction_hashes.keys():
        raise ValueError("scored runs and prediction hashes must match")
    output_runs = {}
    for name, run in runs.items():
        samples = []
        for sample in run["samples"]:
            item = {key: sample[key] for key in SAMPLE_FIELDS}
            item["scores"] = _numeric_tree(sample["scores"])
            samples.append(item)
        output_runs[name] = {"aggregate": _aggregate(run["aggregate"]), "samples": samples}
    source_specs = [{key: spec[key] for key in ("name", "sha256")} for spec in provenance["source_specs"]]
    selected_provenance = {key: provenance[key] for key in PROVENANCE_FIELDS if key in provenance}
    selected_provenance["source_specs"] = source_specs
    selected_provenance["source_selective_sha256"] = source_sha256
    selected_provenance["summarizer_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    # Arbitrary run metadata and comparison witnesses may contain prediction or source text.
    return {"format": "ids-selective-publication-scores-v1", "mode": report["mode"],
            "family_status": report["family_status"], "family_policy": _policy(report["family_policy"]),
            "max_states": report["max_states"], "index_sha256": report["index_sha256"],
            "bootstrap_iterations": report["bootstrap_iterations"], "bootstrap_seed": report["bootstrap_seed"],
            "sources": _sources(report["sources"]), "runs": output_runs,
            "paired_differences": _paired(report["paired_differences"]), "provenance": selected_provenance}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        data = args.score.read_bytes()
        result = summarize(json.loads(data), hashlib.sha256(data).hexdigest())
        encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
