"""Score paired IDS predictions. Run with ``python -m benchmark.score``.

Each reference has an ``ids`` string. A reviewed row may additionally supply
``reviewed_references``, a nonempty list of alternative IDS strings for that
same image. Strict scoring has no component-family aliases. An optional JSON
family policy must contain a nonempty ``policy`` description and ``rules``;
each rule has ``components`` and ``positions`` (paths of [operator, index]
steps), or ``contexts`` (parent [operator, index] pairs at any depth), using
the evaluator's normalized operators. The policy and its SHA-256
are recorded in the result. No alias is inferred from the character or font.

Raw exact and recall_at_5 compare the preferred ``ids`` on all samples.
Parseable exact and recall_at_5 exclude samples with an unparseable preferred
reference; unparseable predictions score zero. Separate reference-set metrics
include reviewed alternatives. Structural metrics exclude samples with no parseable reference; prediction
errors and unparseable predictions score zero. Tree-edit excludes references
exceeding the evaluator's bound; predictions exceeding it score zero. Confidence
intervals resample characters, retaining all images of each sampled character;
paired differences use the same draws.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import platform
import random
import unicodedata

from .ids_evaluator import ARITY, FamilyRule, Leaf, evaluate, parse_ids

METRICS = ("raw_exact", "recall_at_5", "parseable_exact", "parseable_recall_at_5", "reference_set_exact", "reference_set_recall_at_5", "structural_match", "family_match",
           "structural_recall_at_5", "family_recall_at_5", "skeleton_accuracy", "component_precision", "component_recall",
           "component_f1", "tree_edit_similarity")


def parse_jsonl(data, path):
    rows = []
    with io.StringIO(data.decode("utf-8"), newline=None) as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected object")
            rows.append(row)
    return rows


def read_jsonl(path):
    return parse_jsonl(Path(path).read_bytes(), path)


def index_rows(rows, label):
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("sample_id"), str) or not row["sample_id"]:
            raise ValueError(f"{label}: missing or invalid sample_id")
        key = row["sample_id"]
        if key in result:
            raise ValueError(f"{label}: duplicate sample_id {key!r}")
        result[key] = row
    if not result:
        raise ValueError(f"{label}: no rows")
    return result


def require_same_ids(expected, actual, label):
    missing, extra = sorted(expected.keys() - actual.keys()), sorted(actual.keys() - expected.keys())
    if missing or extra:
        raise ValueError(f"{label}: missing IDs {missing}; extra IDs {extra}")


def reference_texts(row):
    for key in ("char", "font", "ids", "review_status"):
        if not isinstance(row.get(key), str) or not row[key]:
            raise ValueError(f"reference {row['sample_id']}: invalid {key}")
    char = row["char"]
    if len(char) != 1 or 0xD800 <= ord(char) <= 0xDFFF:
        raise ValueError(f"reference {row['sample_id']}: char must be one Unicode scalar")
    texts = [row["ids"]]
    if "reviewed_references" in row:
        alternatives = row["reviewed_references"]
        if row["review_status"] != "reviewed":
            raise ValueError("reviewed_references require review_status='reviewed'")
        if not isinstance(alternatives, list) or not alternatives or any(not isinstance(x, str) or not x for x in alternatives):
            raise ValueError("reviewed_references must be a nonempty list of strings")
        texts.extend(alternatives)
    if len(set(texts)) != len(texts):
        raise ValueError("duplicate reference text")
    return texts


def candidates_for(row):
    status = row.get("status")
    candidates = row.get("candidates")
    if status not in ("ok", "error") or not isinstance(candidates, list):
        raise ValueError(f"prediction {row['sample_id']}: invalid status or candidates")
    if status == "error":
        if candidates:
            raise ValueError("failed prediction must have no candidates")
        return []
    if not candidates:
        raise ValueError("successful prediction must have candidates")
    result = []
    for rank, candidate in enumerate(candidates, 1):
        if (not isinstance(candidate, dict) or not isinstance(candidate.get("text"), str)
                or type(candidate.get("rank")) is not int or candidate["rank"] != rank):
            raise ValueError(f"prediction {row['sample_id']}: invalid ranked candidate {rank}")
        result.append(candidate["text"])
    return result


def load_policy(path):
    data = Path(path).read_bytes()
    payload = json.loads(data)
    if not isinstance(payload, dict) or not isinstance(payload.get("policy"), str) or not payload["policy"].strip():
        raise ValueError("family policy requires a nonempty policy description")
    if not isinstance(payload.get("rules"), list) or not payload["rules"]:
        raise ValueError("family policy requires nonempty rules")
    rules = []
    for rule in payload["rules"]:
        if not isinstance(rule, dict):
            raise ValueError("invalid family rule")
        components = rule.get("components")
        positions, contexts = rule.get("positions", []), rule.get("contexts", [])
        if (not isinstance(components, list) or any(not isinstance(c, str) or not isinstance(parse_ids(c).tree, Leaf) for c in components)
                or len(components) != 2 or len(set(components)) != 2):
            raise ValueError("family rule requires exactly two distinct component strings")
        if not isinstance(positions, list) or not isinstance(contexts, list) or not (positions or contexts):
            raise ValueError("family rule requires positions or contexts")
        def step_tuple(step):
            if (not isinstance(step, list) or len(step) != 2 or not isinstance(step[0], str)
                    or not step[0] or type(step[1]) is not int or step[1] < 0):
                raise ValueError("invalid family path step")
            operator, index = step
            if operator not in ("H", "V"):
                if operator not in ARITY or operator in "⿰⿱⿲⿳" or index >= ARITY[operator]:
                    raise ValueError("invalid normalized family operator or child index")
            return tuple(step)
        paths = []
        for path in positions:
            if not isinstance(path, list) or not path:
                raise ValueError("family paths must contain at least one step; root aliases are forbidden")
            paths.append(tuple(step_tuple(step) for step in path))
        rules.append(FamilyRule(frozenset(components), frozenset(paths),
                                frozenset(step_tuple(step) for step in contexts)))
    return rules, {"sha256": hashlib.sha256(data).hexdigest(), "document": payload}


def score_sample(ref, prediction, family_rules=None):
    references = reference_texts(ref)
    candidates = candidates_for(prediction)
    # Empty prediction deliberately goes through the parser to record its status.
    evaluation = evaluate(candidates[0] if candidates else "", references,
                          family_rules=family_rules, tree_edit=True)
    parsed = asdict(evaluation)
    scorable = "valid" in evaluation.reference_statuses
    valid_refs = [text for text, status in zip(references, evaluation.reference_statuses) if status == "valid"]
    # A reference above the tree-edit cap makes this diagnostic unavailable;
    # a prediction above the cap remains a zero in an eligible denominator.
    tree_reference_status = (evaluate(valid_refs[0], references, family_rules=family_rules,
                                      tree_edit=True).tree_edit_status if valid_refs else "unscorable")
    tree_eligible = tree_reference_status == "valid"
    preferred_valid = evaluation.reference_statuses[0] == "valid"
    scores = {"raw_exact": float(bool(candidates) and candidates[0] == ref["ids"]),
              "recall_at_5": float(ref["ids"] in candidates[:5]),
              "parseable_exact": float(bool(candidates) and evaluation.prediction_status == "valid"
                                       and candidates[0] == ref["ids"]) if preferred_valid else None,
              "parseable_recall_at_5": float(any(text == ref["ids"] and parse_ids(text).status == "valid"
                                                   for text in candidates[:5])) if preferred_valid else None,
              "reference_set_exact": float(bool(candidates) and candidates[0] in references),
              "reference_set_recall_at_5": float(any(text in references for text in candidates[:5]))}
    ranked_evaluations = [evaluation] + [evaluate(text, references, family_rules=family_rules)
                                           for text in candidates[1:5]] if candidates else []
    scores["structural_recall_at_5"] = float(any(e.structural_match for e in ranked_evaluations)) if scorable else None
    scores["family_recall_at_5"] = float(any(e.family_match for e in ranked_evaluations)) if scorable and family_rules is not None else None
    for metric in ("structural_match", "family_match", "skeleton_accuracy", "component_precision",
                   "component_recall", "component_f1", "tree_edit_similarity"):
        value = getattr(evaluation, metric)
        eligible = tree_eligible if metric == "tree_edit_similarity" else scorable
        if metric == "family_match" and family_rules is None:
            eligible = False
        scores[metric] = float(value or 0) if eligible else None
    return {"sample_id": ref["sample_id"], "char": ref["char"], "font": ref["font"],
            "review_status": ref["review_status"], "prediction_run_status": prediction["status"],
            "candidate_count": len(candidates), "reference_scorable": scorable,
            "prediction_status": evaluation.prediction_status,
            "reference_statuses": list(evaluation.reference_statuses),
            "tree_reference_status": tree_reference_status,
            "tree_edit_status": parsed["tree_edit_status"], "scores": scores}


def summary(samples):
    by_char = defaultdict(list)
    for sample in samples:
        by_char[sample["char"]].append(sample)
    result = {}
    for metric in METRICS:
        values = [s["scores"][metric] for s in samples if s["scores"][metric] is not None]
        char_values = []
        for group in by_char.values():
            group_values = [s["scores"][metric] for s in group if s["scores"][metric] is not None]
            if group_values:
                char_values.append(sum(group_values) / len(group_values))
        result[metric] = {"image_macro": sum(values) / len(values) if values else None,
                          "image_denominator": len(values),
                          "character_macro": sum(char_values) / len(char_values) if char_values else None,
                          "character_denominator": len(char_values)}
    return result


def aggregate(samples):
    by_font = defaultdict(list)
    by_review_status = defaultdict(list)
    for sample in samples:
        by_font[sample["font"]].append(sample)
        by_review_status[sample["review_status"]].append(sample)
    return {"sample_count": len(samples), "character_count": len({s['char'] for s in samples}),
            "cluster_count": len({s['char'] for s in samples}),
            "candidate_depth": {"minimum": min((s["candidate_count"] for s in samples), default=None),
                                "maximum": max((s["candidate_count"] for s in samples), default=None),
                                "at_least_5_samples": sum(s["candidate_count"] >= 5 for s in samples),
                                "under_5_samples": sum(s["candidate_count"] < 5 for s in samples)},
            "reference_scorable_samples": sum(s["reference_scorable"] for s in samples),
            "reference_unscorable_samples": sum(not s["reference_scorable"] for s in samples),
            "review_status_counts": dict(sorted(Counter(s["review_status"] for s in samples).items())),
            "review_status_proportions": {status: count / len(samples) for status, count in sorted(
                Counter(s["review_status"] for s in samples).items())} if samples else {},
            "reference_status_counts": {status: sum(s["reference_statuses"].count(status) for s in samples)
                                        for status in ("valid", "invalid", "unsupported")},
            "reference_samples_with_status": {status: sum(status in s["reference_statuses"] for s in samples)
                                               for status in ("valid", "invalid", "unsupported")},
            "tree_reference_status_counts": dict(sorted(Counter(s["tree_reference_status"] for s in samples).items())),
            "prediction_status_counts": {status: sum(s["prediction_status"] == status for s in samples)
                                         for status in ("valid", "invalid", "unsupported")},
            "prediction_run_status_counts": dict(sorted(Counter(s["prediction_run_status"] for s in samples).items())),
            "tree_edit_status_counts": dict(sorted(Counter(s["tree_edit_status"] for s in samples).items())),
            "candidate_count_distribution": dict(sorted(Counter(s["candidate_count"] for s in samples).items())),
            "scores": summary(samples),
            "per_review_status": {status: {"sample_count": len(group),
                                           "character_count": len({s['char'] for s in group}),
                                           "scores": summary(group)}
                                  for status, group in sorted(by_review_status.items())},
            "per_font": {font: {"sample_count": len(group), "character_count": len({s['char'] for s in group}),
                                "scores": summary(group)} for font, group in sorted(by_font.items())}}


def percentile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def paired_bootstrap(first, second, *, iterations=2000, seed=0):
    """Return first-minus-second scores and percentile character-cluster CIs."""
    if type(iterations) is not int or iterations <= 0:
        raise ValueError("bootstrap iterations must be positive")
    a = {s["sample_id"]: s for s in first}
    b = {s["sample_id"]: s for s in second}
    if len(a) != len(first) or len(b) != len(second):
        raise ValueError("duplicate sample in paired scores")
    require_same_ids(a, b, "paired scores")
    groups = defaultdict(list)
    for key in sorted(a):
        if a[key]["char"] != b[key]["char"]:
            raise ValueError("paired character mismatch")
        groups[a[key]["char"]].append(key)
    chars = sorted(groups)
    if not chars:
        raise ValueError("no paired samples")
    # Per-character sufficient statistics also preserve image weighting.
    stats = {}
    for metric in METRICS:
        stats[metric] = {}
        for char in chars:
            differences = []
            for key in groups[char]:
                x, y = a[key]["scores"][metric], b[key]["scores"][metric]
                if (x is None) != (y is None):
                    raise ValueError("paired score denominators differ")
                if x is not None:
                    differences.append(x - y)
            stats[metric][char] = (sum(differences), len(differences))
    draws = {metric: {"image_macro": [], "character_macro": []} for metric in METRICS}
    rng = random.Random(seed)
    # NumPy is an optional accelerator; random draws use the same stdlib stream
    # in both paths. Batching bounds temporary memory for large character sets.
    try:
        import numpy as np
    except ImportError:
        np = None
    arrays = {}
    if np is not None:
        for metric in METRICS:
            pairs = [stats[metric][char] for char in chars]
            sums = np.array([x for x, _ in pairs], dtype=float)
            counts = np.array([n for _, n in pairs], dtype=float)
            means = np.divide(sums, counts, out=np.zeros_like(sums), where=counts != 0)
            arrays[metric] = (sums, counts, means, (counts != 0).astype(float))
    for start in range(0, iterations, 64):
        indices = [[rng.randrange(len(chars)) for _ in chars] for _ in range(min(64, iterations - start))]
        if np is not None:
            selected = np.asarray(indices)
            for metric in METRICS:
                sums, counts, means, eligible = arrays[metric]
                totals = sums[selected].sum(axis=1)
                denominators = counts[selected].sum(axis=1)
                char_totals = means[selected].sum(axis=1)
                char_counts = eligible[selected].sum(axis=1)
                for total, denom, char_total, char_count in zip(totals, denominators, char_totals, char_counts):
                    if denom:
                        draws[metric]["image_macro"].append(float(total / denom))
                        draws[metric]["character_macro"].append(float(char_total / char_count))
        else:
            for draw in indices:
                sampled = [chars[index] for index in draw]
                for metric in METRICS:
                    pairs = [stats[metric][char] for char in sampled if stats[metric][char][1]]
                    if pairs:
                        draws[metric]["image_macro"].append(sum(x for x, _ in pairs) / sum(n for _, n in pairs))
                        draws[metric]["character_macro"].append(sum(x / n for x, n in pairs) / len(pairs))
    output = {}
    for metric in METRICS:
        pairs = [pair for pair in stats[metric].values() if pair[1]]
        output[metric] = {}
        for weighting in ("image_macro", "character_macro"):
            vals = draws[metric][weighting]
            estimate = (sum(x for x, _ in pairs) / sum(n for _, n in pairs) if weighting == "image_macro"
                        else sum(x / n for x, n in pairs) / len(pairs)) if pairs else None
            output[metric][weighting] = {"difference": estimate,
                "ci95": [percentile(vals, .025), percentile(vals, .975)] if vals else None,
                "valid_replicates": len(vals)}
    return {"iterations": iterations, "seed": seed, "cluster": "char", "cluster_count": len(chars), "scores": output}


def score_runs(inputs, references, runs, *, family_rules=None, iterations=2000, seed=0):
    expected = index_rows(inputs, "inputs")
    refs = index_rows(references, "references")
    require_same_ids(expected, refs, "references")
    if not runs:
        raise ValueError("at least one prediction run is required")
    scored = {}
    for name, rows in runs.items():
        predictions = index_rows(rows, f"predictions {name}")
        require_same_ids(expected, predictions, f"predictions {name}")
        samples = [score_sample(refs[key], predictions[key], family_rules) for key in sorted(expected)]
        scored[name] = {"samples": samples, "aggregate": aggregate(samples)}
    pairs = {}
    names = sorted(scored)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            first_samples = scored[first]["samples"]
            second_samples = scored[second]["samples"]
            comparison = paired_bootstrap(first_samples, second_samples, iterations=iterations, seed=seed)
            depths = [(a["candidate_count"], b["candidate_count"]) for a, b in zip(first_samples, second_samples)]
            comparison["top5_candidate_depth"] = {
                "sample_count": len(depths),
                "both_at_least_5_samples": sum(a >= 5 and b >= 5 for a, b in depths),
                "first_under_5_samples": sum(a < 5 for a, _ in depths),
                "second_under_5_samples": sum(b < 5 for _, b in depths),
                "unequal_depth_samples": sum(a != b for a, b in depths),
                "all_samples_have_five_candidates_in_both_runs": all(a >= 5 and b >= 5 for a, b in depths),
                "note": "Candidate counts alone do not establish comparable decoding policies.",
            }
            pairs[f"{first} - {second}"] = comparison
    return {"format": "ids-scores-v1", "runs": scored, "paired_differences": pairs}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", type=Path, action="append", required=True, help="prediction directory; repeat for paired comparisons")
    parser.add_argument("--output", type=Path, required=True, help="new JSON output file")
    parser.add_argument("--family-policy", type=Path)
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        if args.bootstrap_iterations <= 0:
            raise ValueError("bootstrap iterations must be positive")
        names = [path.name for path in args.run]
        if len(set(names)) != len(names):
            raise ValueError("run directory names must be unique")
        rules, policy = load_policy(args.family_policy) if args.family_policy else (None, None)
        input_path, reference_path = args.dataset / "inputs.jsonl", args.dataset / "references.jsonl"
        digest_bytes = lambda data: hashlib.sha256(data).hexdigest()
        digest = lambda path: digest_bytes(path.read_bytes())
        input_bytes, reference_bytes = input_path.read_bytes(), reference_path.read_bytes()
        manifest_hash = digest_bytes(input_bytes)
        reference_hash = digest_bytes(reference_bytes)
        metadata, run_hashes, prediction_hashes, predictions = {}, {}, {}, {}
        for name, path in zip(names, args.run):
            run_bytes = (path / "run.json").read_bytes()
            prediction_bytes = (path / "predictions.jsonl").read_bytes()
            run_metadata = json.loads(run_bytes)
            if not isinstance(run_metadata, dict) or run_metadata.get("manifest_sha256") != manifest_hash:
                raise ValueError(f"run {name}: manifest_sha256 does not match dataset inputs")
            prediction_hash = digest_bytes(prediction_bytes)
            if ("output_predictions_sha256" in run_metadata and
                    run_metadata["output_predictions_sha256"] != prediction_hash):
                raise ValueError(f"run {name}: output_predictions_sha256 does not match predictions")
            metadata[name] = run_metadata
            run_hashes[name] = digest_bytes(run_bytes)
            prediction_hashes[name] = prediction_hash
            predictions[name] = parse_jsonl(prediction_bytes, path / "predictions.jsonl")
        result = score_runs(parse_jsonl(input_bytes, input_path), parse_jsonl(reference_bytes, reference_path),
                            predictions, family_rules=rules, iterations=args.bootstrap_iterations, seed=args.seed)
        result["family_policy"] = policy
        result["family_status"] = "enabled" if policy is not None else "disabled"
        result["provenance"] = {"inputs_sha256": manifest_hash, "references_sha256": reference_hash,
                                "run_sha256": run_hashes,
                                "scorer_sha256": digest(Path(__file__)),
                                "evaluator_sha256": digest(Path(__file__).with_name("ids_evaluator.py")),
                                "prediction_sha256": prediction_hashes,
                                "python_version": platform.python_version(),
                                "runtime_unicode_database_version": unicodedata.unidata_version,
                                "evaluator_unicode_version": "17.0.0",
                                "runs": metadata}
        # Exclusive creation prevents clobbering dataset, run, or prior score files.
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
