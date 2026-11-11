"""Experimental bounded selective-expansion sensitivity, not image correctness.

Run with ``python -m benchmark.score_selective --dataset DIR --run DIR
--source-spec FILE --output FILE``. Runs and pinned source specs may be repeated.
An explicit family policy is optional. Bounds use the fixed set of samples with
at least one valid reference; prediction failures remain in that denominator.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import random
import unicodedata

from .expansion import _serialize, compare_selective
from .score import candidates_for, index_rows, load_policy, percentile, reference_texts, require_same_ids
from .score_expansion import METRICS, any_match, load_specs, score_sample as score_expansion_sample, sha256

# Tri-state diagnostic availability depends on the prediction, so it must not
# determine an aggregate denominator. The diagnostic values remain per sample.
BASELINE_METRICS = tuple(metric for metric in METRICS
                         if metric not in ("expansion_match", "family_match", "expansion_family_match"))
SELECTIVE_METRICS = ("selective_hit", "selective_upper", "eligible_selective_hit", "eligible_selective_upper",
                     "selective_recall_at_5", "selective_recall_at_5_upper",
                     "eligible_selective_recall_at_5", "eligible_selective_recall_at_5_upper")


def index_hash(index):
    """Hash the loaded index, including source metadata and opaque definitions."""
    obj = {"definitions": {key: _serialize(value) for key, value in sorted(index.definitions.items())},
           "opaque_reasons": dict(sorted(index.opaque_reasons.items())), "metadata": index.metadata}
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _score_one(ref, prediction, index, family_rules=None, max_states=256):
    if type(max_states) is not int or not 1 <= max_states <= 10000:
        raise ValueError("max_states must be an integer from 1 to 10000")
    sample = score_expansion_sample(ref, prediction, index, family_rules)
    comparisons = []
    if sample["prediction"] is not None:
        for reference in reference_texts(ref):
            result = compare_selective(sample["prediction"], reference, index=index,
                                       target=ref["char"], family_rules=family_rules,
                                       max_states=max_states)
            comparisons.append({"reference_ids": reference, **asdict(result)})
        if sample["prediction_status"] == "invalid":
            match, status = False, "invalid_prediction"
        else:
            match = any_match([item["match"] for item in comparisons])
            status = "matched" if match is True else "indeterminate" if match is None else "no_match"
    else:
        match, status = False, "no_prediction"
    scores = sample["scores"]
    # Family-inclusive baseline is unavailable when no policy was supplied.
    baseline = scores["combined_hit"] if family_rules is not None else scores["relaxed_hit"]
    upper = scores["combined_upper"] if family_rules is not None else scores["relaxed_upper"]
    hit = baseline or match is True
    upper_hit = upper or match is not False
    eligible = sample["reference_eligible"]
    scores.update({"selective_match": match, "selective_hit": hit, "selective_upper": upper_hit,
                   "eligible_selective_hit": hit if eligible else None,
                   "eligible_selective_upper": upper_hit if eligible else None})
    sample.update({"selective_status": status, "selective_comparisons": comparisons,
                   "selective_states_visited": sum(item["states_visited"] for item in comparisons)})
    return sample


def score_sample(ref, prediction, index, family_rules=None, max_states=256):
    sample = _score_one(ref, prediction, index, family_rules, max_states)
    candidates = candidates_for(prediction)[:5]
    results = []
    if candidates:
        results.append(sample)
        for text in candidates[1:]:
            single = {"sample_id": prediction["sample_id"], "status": "ok",
                      "candidates": [{"rank": 1, "text": text}]}
            results.append(_score_one(ref, single, index, family_rules, max_states))
    hit = any(row["scores"]["selective_hit"] for row in results)
    upper = any(row["scores"]["selective_upper"] for row in results)
    matched_rank = next((i for i, row in enumerate(results, 1) if row["scores"]["selective_hit"]), None)
    sample["scores"].update({"selective_recall_at_5": hit, "selective_recall_at_5_upper": upper,
                             "eligible_selective_recall_at_5": hit if sample["reference_eligible"] else None,
                             "eligible_selective_recall_at_5_upper": upper if sample["reference_eligible"] else None})
    sample.update({"selective_recall_at_5_candidate_count": len(results),
                   "selective_recall_at_5_matched_rank": matched_rank,
                   "selective_recall_at_5_candidates": [
                       {"rank": i, "prediction_status": row["prediction_status"],
                        "selective_status": row["selective_status"],
                        "selective_states_visited": row["selective_states_visited"],
                        "comparisons": row["comparisons"],
                        "selective_comparisons": row["selective_comparisons"],
                        "selective_hit": row["scores"]["selective_hit"],
                        "selective_upper": row["scores"]["selective_upper"]}
                       for i, row in enumerate(results, 1)]})
    return sample


def summary(samples):
    groups = defaultdict(list)
    for row in samples:
        groups[row["char"]].append(row)
    result = {}
    for metric in BASELINE_METRICS + SELECTIVE_METRICS:
        values = [row["scores"][metric] for row in samples if row["scores"][metric] is not None]
        means = []
        for group in groups.values():
            included = [row["scores"][metric] for row in group if row["scores"][metric] is not None]
            if included:
                means.append(sum(included) / len(included))
        result[metric] = {"image_macro": sum(values) / len(values) if values else None,
                          "image_denominator": len(values),
                          "image_coverage": len(values) / len(samples) if samples else None,
                          "character_macro": sum(means) / len(means) if means else None,
                          "character_denominator": len(means),
                          "character_coverage": len(means) / len(groups) if groups else None}
    return result


def aggregate(samples):
    by_font = defaultdict(list)
    for row in samples:
        by_font[row["font"]].append(row)
    return {"sample_count": len(samples), "character_count": len({row["char"] for row in samples}),
            "reference_eligible_samples": sum(row["reference_eligible"] for row in samples),
            "selective_status_counts": dict(sorted(Counter(row["selective_status"] for row in samples).items())),
            "selective_states_visited": sum(row["selective_states_visited"] for row in samples),
            "indeterminate_after_baseline": sum(row["scores"]["selective_hit"] != row["scores"]["selective_upper"] for row in samples),
            "scores": summary(samples),
            "per_font": {font: {"sample_count": len(rows), "character_count": len({r["char"] for r in rows}),
                                "scores": summary(rows)} for font, rows in sorted(by_font.items())}}


def paired_bootstrap(first, second, *, iterations, seed):
    """Paired first-minus-second bounds, resampling reference-eligible characters."""
    if type(iterations) is not int or iterations <= 0:
        raise ValueError("bootstrap iterations must be positive")
    a, b = index_rows(first, "first scores"), index_rows(second, "second scores")
    require_same_ids(a, b, "paired scores")
    metrics = ("eligible_selective_hit", "eligible_selective_upper",
               "eligible_selective_recall_at_5", "eligible_selective_recall_at_5_upper")
    by_char = defaultdict(lambda: {metric: [0, 0] for metric in metrics})
    for key in sorted(a):
        left, right = a[key], b[key]
        if left["char"] != right["char"]:
            raise ValueError("paired character mismatch")
        if left["reference_eligible"] != right["reference_eligible"]:
            raise ValueError("paired reference eligibility mismatch")
        for metric in metrics:
            x, y = left["scores"][metric], right["scores"][metric]
            if (x is None) != (y is None) or (x is not None) != left["reference_eligible"]:
                raise ValueError("paired reference eligibility mismatch")
            if x is not None:
                pair = by_char[left["char"]][metric]
                pair[0] += int(x) - int(y)
                pair[1] += 1
    chars = sorted(by_char)
    draws = {metric: {"image_macro": [], "character_macro": []} for metric in metrics}
    rng = random.Random(seed)
    for _ in range(iterations):
        if not chars:
            break
        counts = Counter(rng.randrange(len(chars)) for _ in chars)
        for metric in metrics:
            pairs = [(by_char[chars[i]][metric], count) for i, count in counts.items()]
            draws[metric]["image_macro"].append(sum(p[0] * n for p, n in pairs) / sum(p[1] * n for p, n in pairs))
            draws[metric]["character_macro"].append(sum(p[0] / p[1] * n for p, n in pairs) / len(chars))
    scores = {}
    for metric in metrics:
        pairs = [by_char[char][metric] for char in chars]
        scores[metric] = {"paired_image_denominator": sum(p[1] for p in pairs),
                          "paired_character_denominator": len(pairs)}
        for weighting in ("image_macro", "character_macro"):
            values = draws[metric][weighting]
            estimate = ((sum(p[0] for p in pairs) / sum(p[1] for p in pairs)) if weighting == "image_macro"
                        else (sum(p[0] / p[1] for p in pairs) / len(pairs))) if pairs else None
            scores[metric][weighting] = {"difference": estimate,
                                         "ci95": [percentile(values, .025), percentile(values, .975)] if values else None,
                                         "valid_replicates": len(values)}
    return {"cluster": "char", "coverage": "fixed reference eligibility", "iterations": iterations,
            "seed": seed, "scores": scores,
            "interpretation": "Intervals describe paired differences in the reported lower and upper bounds, not confidence intervals for true accuracy."}


def score_runs(inputs, references, runs, *, index, family_rules=None, max_states=256, iterations=0, seed=0):
    if type(max_states) is not int or not 1 <= max_states <= 10000:
        raise ValueError("max_states must be an integer from 1 to 10000")
    if type(iterations) is not int or iterations < 0:
        raise ValueError("bootstrap iterations must be nonnegative")
    expected, refs = index_rows(inputs, "inputs"), index_rows(references, "references")
    require_same_ids(expected, refs, "references")
    if not runs:
        raise ValueError("at least one prediction run is required")
    scored = {}
    for name, rows in runs.items():
        predictions = index_rows(rows, f"predictions {name}")
        require_same_ids(expected, predictions, f"predictions {name}")
        samples = [score_sample(refs[key], predictions[key], index, family_rules, max_states)
                   for key in sorted(expected)]
        scored[name] = {"samples": samples, "aggregate": aggregate(samples)}
    names = sorted(scored)
    pairs = {f"{a} - {b}": paired_bootstrap(scored[a]["samples"], scored[b]["samples"], iterations=iterations, seed=seed)
             for i, a in enumerate(names) for b in names[i + 1:]} if iterations else {}
    return {"format": "ids-selective-scores-v1",
            "mode": "experimental-decomposition-allowance-not-image-correctness",
            "family_status": "enabled" if family_rules is not None else "disabled",
            "max_states": max_states, "sources": index.metadata, "index_sha256": index_hash(index),
            "bootstrap_iterations": iterations, "bootstrap_seed": seed if iterations else None,
            "runs": scored, "paired_differences": pairs}


def _jsonl_bytes(data, label):
    rows = []
    for number, line in enumerate(data.decode("utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label}:{number}: invalid JSON") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{label}:{number}: expected object")
        rows.append(row)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--source-spec", type=Path, action="append", required=True)
    parser.add_argument("--family-policy", type=Path)
    parser.add_argument("--max-states", type=int, default=256)
    parser.add_argument("--bootstrap-iterations", type=int, nargs="?", const=2000, default=0,
                        help="opt in to paired character bootstrap (default 2000 draws when supplied)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        names = [path.name for path in args.run]
        if len(set(names)) != len(names):
            raise ValueError("run directory names must be unique")
        code_paths = {"scorer_sha256": Path(__file__),
                      "expansion_scorer_sha256": Path(__file__).with_name("score_expansion.py"),
                      "expansion_sha256": Path(__file__).with_name("expansion.py"),
                      "score_helpers_sha256": Path(__file__).with_name("score.py"),
                      "evaluator_sha256": Path(__file__).with_name("ids_evaluator.py")}
        code_hashes = {key: sha256(path) for key, path in code_paths.items()}
        index, spec_documents = load_specs(args.source_spec)
        rules, policy = load_policy(args.family_policy) if args.family_policy else (None, None)
        input_path, ref_path = args.dataset / "inputs.jsonl", args.dataset / "references.jsonl"
        input_data, ref_data = input_path.read_bytes(), ref_path.read_bytes()
        digest = lambda data: hashlib.sha256(data).hexdigest()
        manifest_hash, reference_hash = digest(input_data), digest(ref_data)
        metadata, prediction_hashes, run_hashes, predictions = {}, {}, {}, {}
        for name, path in zip(names, args.run):
            run_data = (path / "run.json").read_bytes()
            run = json.loads(run_data)
            if not isinstance(run, dict) or run.get("manifest_sha256") != manifest_hash:
                raise ValueError(f"run {name}: manifest_sha256 does not match dataset inputs")
            prediction_data = (path / "predictions.jsonl").read_bytes()
            prediction_hash = digest(prediction_data)
            if ("output_predictions_sha256" in run and
                    run["output_predictions_sha256"] != prediction_hash):
                raise ValueError(f"run {name}: output_predictions_sha256 does not match predictions")
            metadata[name] = run
            run_hashes[name] = digest(run_data)
            prediction_hashes[name] = prediction_hash
            predictions[name] = _jsonl_bytes(prediction_data, path / "predictions.jsonl")
        result = score_runs(_jsonl_bytes(input_data, input_path), _jsonl_bytes(ref_data, ref_path), predictions,
                            index=index, family_rules=rules, max_states=args.max_states,
                            iterations=args.bootstrap_iterations, seed=args.seed)
        if sha256(input_path) != manifest_hash or sha256(ref_path) != reference_hash:
            raise ValueError("dataset manifests changed during scoring")
        for name, path in zip(names, args.run):
            if sha256(path / "predictions.jsonl") != prediction_hashes[name]:
                raise ValueError(f"run {name}: predictions changed during scoring")
            if sha256(path / "run.json") != run_hashes[name]:
                raise ValueError(f"run {name}: run metadata changed during scoring")
        for key, path in code_paths.items():
            if sha256(path) != code_hashes[key]:
                raise ValueError(f"source code changed during scoring: {path.name}")
        result["family_policy"] = policy
        result["provenance"] = {
            "inputs_sha256": manifest_hash, "references_sha256": reference_hash,
            **code_hashes,
            "index_sha256": result["index_sha256"], "source_specs": spec_documents,
            "runs": metadata, "run_manifest_sha256": run_hashes,
            "prediction_sha256": prediction_hashes,
            "python_version": platform.python_version(), "unicode_version": unicodedata.unidata_version,
            "evaluator_unicode_version": "17.0.0"}
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
