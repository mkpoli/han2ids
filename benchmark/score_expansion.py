"""Exploratory expansion sensitivity, not image-gold correctness.

Run ``python -m benchmark.score_expansion --dataset DIR --run DIR
--source-spec FILE --output FILE``. Repeat --run and --source-spec as needed.
Each source spec is a JSON object with path, sha256, provenance and license;
relative source paths are resolved against the spec file. An optional explicit
--family-policy is applied separately before and after expansion. The top-ranked
prediction is compared to the preferred and reviewed per-image references.
The cumulative columns are strict_hit, family_only_hit, relaxed_hit (expansion
only), and combined_hit. The latter two preserve earlier hits even if a later
comparison is indeterminate. Indeterminate comparisons count as misses in
lower bounds and hits in upper bounds. Reference-eligible bounds share a
prediction-independent sample set. Optional paired intervals resample character
clusters on that fixed set.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import json
import platform
from pathlib import Path
import random
import unicodedata

from .expansion import SourceSpec, compare, load_sources
from .ids_evaluator import evaluate
from .score import candidates_for, index_rows, load_policy, parse_jsonl, percentile, reference_texts, require_same_ids

METRICS = ("raw_exact", "reference_set_exact", "structural_match", "strict_hit", "expansion_match",
           "added_hit", "relaxed_hit", "relaxed_upper", "family_match", "family_only_hit",
           "family_only_upper", "expansion_family_match", "combined_hit", "combined_upper",
           "eligible_strict_hit", "eligible_added_hit", "eligible_relaxed_hit", "eligible_relaxed_upper",
           "eligible_family_only_hit", "eligible_family_only_upper", "eligible_combined_hit", "eligible_combined_upper")
# Tri-state diagnostic coverage depends on the prediction; it is not paired.
PAIRED_METRICS = tuple(metric for metric in METRICS
                       if metric not in ("expansion_match", "family_match", "expansion_family_match"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_specs(paths):
    specs, documents = [], []
    for path in paths:
        path = Path(path)
        data = path.read_bytes()
        obj = json.loads(data)
        if not isinstance(obj, dict) or not isinstance(obj.get("path"), str) or not obj["path"].strip():
            raise ValueError(f"source spec {path}: expected object with nonempty path")
        source_path = Path(obj["path"])
        if not source_path.is_absolute():
            source_path = path.parent / source_path
        specs.append(SourceSpec(source_path, obj.get("sha256"), obj.get("provenance"), obj.get("license")))
        documents.append({"name": path.name, "sha256": hashlib.sha256(data).hexdigest()})
    return load_sources(specs), documents


def any_match(values):
    """Three-valued OR across references."""
    return True if True in values else None if None in values else False


def score_sample(ref, prediction, index, family_rules=None):
    references = reference_texts(ref)
    char = ref["char"]
    if len(char) != 1 or 0xD800 <= ord(char) <= 0xDFFF:
        raise ValueError(f"reference {ref['sample_id']}: char must be one Unicode scalar")
    candidates = candidates_for(prediction)
    text = candidates[0] if candidates else ""
    evaluation = evaluate(text, references, family_rules=family_rules)
    raw = bool(candidates) and text == references[0]
    raw_set = bool(candidates) and text in references
    structural = bool(evaluation.structural_match)
    strict = raw_set or structural
    comparisons = []
    if candidates:
        for reference in references:
            options = {"family_rules": family_rules} if family_rules is not None else {}
            comparison = compare(text, reference, index=index, target=char, **options)
            comparisons.append({"reference_ids": reference, **asdict(comparison)})
        if evaluation.prediction_status == "invalid":
            # Malformed output is a definite miss, not an expansion uncertainty.
            expansion, expansion_status = False, "invalid_prediction"
            family = expanded_family = False if family_rules is not None else None
        else:
            expansion = any_match([item["match"] for item in comparisons])
            expansion_status = "match" if expansion is True else "indeterminate" if expansion is None else "no_match"
            if family_rules is not None:
                expanded_family = any_match([item["family_match"] for item in comparisons])
                # Unparseable alternative references leave the upper bound uncertain.
                family = (True if evaluation.family_match is True else
                          None if evaluation.prediction_status != "valid" or
                          any(status != "valid" for status in evaluation.reference_statuses) else False)
            else:
                family = expanded_family = None
    else:
        # An inference error is a miss, not a reference or expansion ambiguity.
        expansion, expansion_status = False, "no_prediction"
        family = expanded_family = False if family_rules is not None else None
    relaxed = strict or expansion is True
    upper = strict or expansion is not False
    added = not strict and expansion is True
    family_hit = strict or family is True if family_rules is not None else None
    family_upper = strict or family is not False if family_rules is not None else None
    combined = (family_hit or relaxed or expanded_family is True) if family_rules is not None else None
    combined_upper = (family_upper or upper or expanded_family is not False) if family_rules is not None else None
    eligible = "valid" in evaluation.reference_statuses
    return {"sample_id": ref["sample_id"], "char": char, "font": ref["font"],
            "review_status": ref["review_status"], "prediction_run_status": prediction["status"],
            "prediction": text if candidates else None, "candidate_count": len(candidates),
            "prediction_status": evaluation.prediction_status, "reference_eligible": eligible,
            "reference_statuses": list(evaluation.reference_statuses),
            "expansion_status": expansion_status, "comparisons": comparisons,
            "scores": {"raw_exact": raw, "reference_set_exact": raw_set,
                       "structural_match": structural if eligible else None, "strict_hit": strict,
                       "expansion_match": expansion, "added_hit": added, "relaxed_hit": relaxed,
                       "relaxed_upper": upper, "family_match": family, "family_only_hit": family_hit,
                       "family_only_upper": family_upper, "expansion_family_match": expanded_family,
                       "combined_hit": combined, "combined_upper": combined_upper,
                       "eligible_strict_hit": strict if eligible else None,
                       "eligible_added_hit": added if eligible else None,
                       "eligible_relaxed_hit": relaxed if eligible else None,
                       "eligible_relaxed_upper": upper if eligible else None,
                       "eligible_family_only_hit": family_hit if eligible else None,
                       "eligible_family_only_upper": family_upper if eligible else None,
                       "eligible_combined_hit": combined if eligible else None,
                       "eligible_combined_upper": combined_upper if eligible else None}}


def summary(samples):
    groups = defaultdict(list)
    for row in samples:
        groups[row["char"]].append(row)
    result = {}
    for metric in METRICS:
        values = [row["scores"][metric] for row in samples if row["scores"][metric] is not None]
        means = []
        for group in groups.values():
            eligible = [row["scores"][metric] for row in group if row["scores"][metric] is not None]
            if eligible:
                means.append(sum(eligible) / len(eligible))
        result[metric] = {"image_macro": sum(values) / len(values) if values else None,
                          "image_denominator": len(values), "image_coverage": len(values) / len(samples) if samples else None,
                          "character_macro": sum(means) / len(means) if means else None,
                          "character_denominator": len(means),
                          "character_coverage": len(means) / len(groups) if groups else None}
    return result


def aggregate(samples):
    by_font = defaultdict(list)
    for row in samples:
        by_font[row["font"]].append(row)
    return {"sample_count": len(samples), "character_count": len({row['char'] for row in samples}),
            "expansion_status_counts": dict(sorted(Counter(row["expansion_status"] for row in samples).items())),
            "reference_eligible_samples": sum(row["reference_eligible"] for row in samples),
            "unscorable_expansion": sum(row["scores"]["expansion_match"] is None for row in samples),
            "indeterminate_after_baseline": sum(row["scores"]["relaxed_hit"] != row["scores"]["relaxed_upper"] for row in samples),
            "strict_hits": sum(row["scores"]["strict_hit"] for row in samples),
            "added_hits": sum(row["scores"]["added_hit"] for row in samples),
            "relaxed_hits_lower": sum(row["scores"]["relaxed_hit"] for row in samples),
            "relaxed_hits_upper": sum(row["scores"]["relaxed_upper"] for row in samples),
            "scores": summary(samples),
            "per_font": {font: {"sample_count": len(rows), "character_count": len({r['char'] for r in rows}),
                                 "scores": summary(rows)} for font, rows in sorted(by_font.items())}}


def paired_bootstrap(first, second, *, iterations, seed):
    """Paired first-minus-second differences on fixed reference eligibility."""
    if type(iterations) is not int or iterations <= 0:
        raise ValueError("bootstrap iterations must be positive")
    a, b = index_rows(first, "first scores"), index_rows(second, "second scores")
    require_same_ids(a, b, "paired scores")
    chars = sorted({row["char"] for row in first})
    by_metric = {metric: defaultdict(lambda: [0, 0]) for metric in PAIRED_METRICS}
    for key in sorted(a):
        x, y = a[key], b[key]
        if x["char"] != y["char"]:
            raise ValueError("paired character mismatch")
        for metric in PAIRED_METRICS:
            p, q = x["scores"][metric], y["scores"][metric]
            if (p is None) != (q is None):
                raise ValueError("paired reference eligibility mismatch")
            if p is not None:
                pair = by_metric[metric][x["char"]]
                pair[0] += int(p) - int(q)
                pair[1] += 1
    stats = {metric: [by_metric[metric].get(char, [0, 0]) for char in chars] for metric in PAIRED_METRICS}
    draws = {metric: {"image_macro": [], "character_macro": []} for metric in PAIRED_METRICS}
    rng = random.Random(seed)
    for _ in range(iterations):
        # Count sampled clusters once, then reuse across all metrics.
        counts = Counter(rng.randrange(len(chars)) for _ in chars)
        for metric in PAIRED_METRICS:
            pairs = [(stats[metric][i], n) for i, n in counts.items() if stats[metric][i][1]]
            if pairs:
                draws[metric]["image_macro"].append(sum(p[0] * n for p, n in pairs) / sum(p[1] * n for p, n in pairs))
                draws[metric]["character_macro"].append(sum(p[0] / p[1] * n for p, n in pairs) / sum(n for _, n in pairs))
    output = {}
    for metric in PAIRED_METRICS:
        pairs = [p for p in stats[metric] if p[1]]
        output[metric] = {"paired_image_denominator": sum(p[1] for p in pairs),
                          "paired_character_denominator": len(pairs)}
        for weighting in ("image_macro", "character_macro"):
            values = draws[metric][weighting]
            estimate = (sum(p[0] for p in pairs) / sum(p[1] for p in pairs) if weighting == "image_macro"
                        else sum(p[0] / p[1] for p in pairs) / len(pairs)) if pairs else None
            output[metric][weighting] = {"difference": estimate,
                "ci95": [percentile(values, .025), percentile(values, .975)] if values else None,
                "valid_replicates": len(values)}
    return {"cluster": "char", "coverage": "fixed reference eligibility", "iterations": iterations,
            "seed": seed, "scores": output}


def score_runs(inputs, references, runs, *, index, family_rules=None, iterations=0, seed=0):
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
        samples = [score_sample(refs[key], predictions[key], index, family_rules) for key in sorted(expected)]
        scored[name] = {"samples": samples, "aggregate": aggregate(samples)}
    names = sorted(scored)
    pairs = {f"{a} - {b}": paired_bootstrap(scored[a]["samples"], scored[b]["samples"], iterations=iterations, seed=seed)
             for i, a in enumerate(names) for b in names[i + 1:]} if iterations else {}
    return {"format": "ids-expansion-scores-v1", "mode": "experimental-decomposition-allowance-not-image-correctness",
            "family_status": "enabled" if family_rules is not None else "disabled",
            "sources": index.metadata, "runs": scored, "paired_differences": pairs}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--source-spec", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--family-policy", type=Path, help="explicit contextual component-family policy")
    parser.add_argument("--bootstrap-iterations", type=int, default=0, help="opt-in paired character-cluster bootstrap")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        names = [path.name for path in args.run]
        if len(set(names)) != len(names):
            raise ValueError("run directory names must be unique")
        index, spec_documents = load_specs(args.source_spec)
        rules, policy = load_policy(args.family_policy) if args.family_policy else (None, None)
        input_path, ref_path = args.dataset / "inputs.jsonl", args.dataset / "references.jsonl"
        input_bytes, reference_bytes = input_path.read_bytes(), ref_path.read_bytes()
        manifest_hash = hashlib.sha256(input_bytes).hexdigest()
        reference_hash = hashlib.sha256(reference_bytes).hexdigest()
        metadata, prediction_hashes, run_hashes, predictions = {}, {}, {}, {}
        for name, path in zip(names, args.run):
            run_bytes = (path / "run.json").read_bytes()
            run_hashes[name] = hashlib.sha256(run_bytes).hexdigest()
            run = json.loads(run_bytes)
            if not isinstance(run, dict) or run.get("manifest_sha256") != manifest_hash:
                raise ValueError(f"run {name}: manifest_sha256 does not match dataset inputs")
            prediction_path = path / "predictions.jsonl"
            prediction_bytes = prediction_path.read_bytes()
            prediction_hash = hashlib.sha256(prediction_bytes).hexdigest()
            if "output_predictions_sha256" in run and run["output_predictions_sha256"] != prediction_hash:
                raise ValueError(f"run {name}: output_predictions_sha256 does not match predictions")
            metadata[name], prediction_hashes[name] = run, prediction_hash
            predictions[name] = parse_jsonl(prediction_bytes, prediction_path)
        result = score_runs(parse_jsonl(input_bytes, input_path), parse_jsonl(reference_bytes, ref_path),
                            predictions, index=index, family_rules=rules,
                            iterations=args.bootstrap_iterations, seed=args.seed)
        result["family_policy"] = policy
        result["provenance"] = {"inputs_sha256": manifest_hash, "references_sha256": reference_hash,
                                "scorer_sha256": sha256(__file__), "expansion_sha256": sha256(Path(__file__).with_name("expansion.py")),
                                "score_helpers_sha256": sha256(Path(__file__).with_name("score.py")),
                                "evaluator_sha256": sha256(Path(__file__).with_name("ids_evaluator.py")),
                                "source_specs": spec_documents, "runs": metadata,
                                "run_manifest_sha256": run_hashes, "prediction_sha256": prediction_hashes,
                                "python_version": platform.python_version(),
                                "unicode_version": unicodedata.unidata_version,
                                "evaluator_unicode_version": "17.0.0"}
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
