import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from benchmark.expansion import SourceSpec, load_sources
from benchmark.ids_evaluator import FamilyRule
from benchmark.score_selective import index_hash, paired_bootstrap, score_runs, score_sample


def ref(sample_id="1", ids="⿰水⿱日月", char="林", **kwargs):
    return {"sample_id": sample_id, "ids": ids, "char": char, "font": "A",
            "review_status": "reviewed" if kwargs else "unreviewed", **kwargs}


def pred(sample_id="1", text="⿰氵木"):
    return {"sample_id": sample_id, "status": "error" if text is None else "ok",
            "candidates": [] if text is None else [{"rank": 1, "text": text}]}


def make_index(tmp_path, text="U+6C35\t氵\t⿱一二\nU+6728\t木\t⿱日月\n"):
    path = tmp_path / "source.tsv"
    path.write_text(text, encoding="utf-8")
    return load_sources([SourceSpec(path, hashlib.sha256(path.read_bytes()).hexdigest(), "test", "test")])


def family():
    return [FamilyRule(frozenset(("氵", "水")), contexts=frozenset((("H", 0),)))]


def test_mixed_selective_witness_and_baseline_monotonic(tmp_path):
    idx = make_index(tmp_path)
    row = score_sample(ref(), pred(), idx, family())
    scores = row["scores"]
    assert not scores["strict_hit"] and not scores["family_only_hit"]
    assert not scores["relaxed_hit"] and not scores["combined_hit"]
    assert scores["selective_match"] is scores["selective_hit"] is scores["selective_upper"] is True
    witness = row["selective_comparisons"][0]
    assert witness["status"] == "matched" and witness["states_visited"] > 0
    assert [step["component"] for step in witness["prediction_trace"]] == ["木"]
    assert witness["reference_trace"] == ()
    assert score_sample(ref(), pred(), idx)["scores"]["selective_hit"] is False
    for expected, text in [("⿰氵木", "⿰氵木"), ("⿰水木", "⿰氵木"),
                           ("⿰氵⿱日月", "⿰氵木"), ("⿰水⿱日月", "⿰氵木")]:
        for rules in (None, family()):
            s = score_sample(ref(ids=expected), pred(text=text), idx, rules)["scores"]
            base = s["combined_hit"] if rules else s["relaxed_hit"]
            upper = s["combined_upper"] if rules else s["relaxed_upper"]
            assert base <= s["selective_hit"] <= s["selective_upper"]
            assert upper <= s["selective_upper"]


def test_cap_invalid_unsupported_and_raw_exact(tmp_path):
    idx = make_index(tmp_path)
    sample = score_sample(ref(), pred(), idx, family(), max_states=1)
    assert sample["selective_status"] == "indeterminate"
    assert "search_limit" in sample["selective_comparisons"][0]["indeterminate_reasons"]
    assert sample["selective_states_visited"] == 1
    assert not sample["scores"]["selective_hit"] and sample["scores"]["selective_upper"]
    for text in ("", "⿰木", "木火", None):
        row = score_sample(ref(), pred(text=text), idx, family())
        assert row["scores"]["selective_match"] is False
        assert row["scores"]["selective_hit"] is row["scores"]["selective_upper"] is False
    row = score_sample(ref(), pred(text="⿰?木"), idx, family())
    assert row["prediction_status"] == "unsupported"
    assert row["scores"]["selective_match"] is None and row["scores"]["selective_upper"]
    row = score_sample(ref(ids="⿰木"), pred(text="⿰木"), idx, family())
    assert row["scores"]["selective_match"] is False
    assert row["scores"]["selective_hit"] is row["scores"]["selective_upper"] is True
    for bound in (0, -1, 10001, True):
        with pytest.raises(ValueError, match="max_states"):
            score_sample(ref(), pred(), idx, max_states=bound)


def test_alternative_references_three_valued_or(tmp_path):
    idx = make_index(tmp_path, "U+7532\t甲\t⿰乙木\nU+4E59\t乙\t⿱甲日\n")
    base = ref(ids="⿰甲火", char="明", reviewed_references=["⿰水火"])
    row = score_sample(base, pred(text="⿰水火"), idx)
    assert [x["match"] for x in row["selective_comparisons"]] == [None, True]
    assert row["scores"]["selective_match"] is True
    row = score_sample(base, pred(text="⿰山火"), idx)
    assert [x["match"] for x in row["selective_comparisons"]] == [None, False]
    assert row["scores"]["selective_match"] is None
    row = score_sample(ref(ids="⿰土火", reviewed_references=["⿰水火"]), pred(text="⿰山火"), idx)
    assert row["scores"]["selective_match"] is False


def test_fixed_reference_denominator_and_ids(tmp_path):
    idx = make_index(tmp_path)
    refs = [ref("1"), ref("2", ids="⿰水木"), ref("3", ids="?")]
    inputs = [{"sample_id": r["sample_id"]} for r in refs]
    runs = {"a": [pred("1"), pred("2", None), pred("3", "?")],
            "b": [pred("1", "?"), pred("2", "⿰水木"), pred("3", "木")]}
    output = score_runs(inputs, refs, runs, index=idx, family_rules=family())
    for run in output["runs"].values():
        for metric in ("eligible_selective_hit", "eligible_selective_upper"):
            assert run["aggregate"]["scores"][metric]["image_denominator"] == 2
            assert run["aggregate"]["scores"][metric]["character_denominator"] == 1
    a = output["runs"]["a"]["aggregate"]["scores"]
    b = output["runs"]["b"]["aggregate"]["scores"]
    assert "expansion_match" not in a and "family_match" not in a
    for metric in a:
        assert a[metric]["image_denominator"] == b[metric]["image_denominator"]
        assert a[metric]["character_denominator"] == b[metric]["character_denominator"]
    for ins, references, predictions in [(inputs + inputs[:1], refs, runs),
                                         (inputs, refs + refs[:1], runs),
                                         (inputs, refs[:-1], runs),
                                         (inputs, refs, {"a": runs["a"] + runs["a"][:1]}),
                                         (inputs, refs, {"a": runs["a"][:-1]}),
                                         (inputs, refs, {"a": [pred("x"), *runs["a"][1:]]})]:
        with pytest.raises(ValueError):
            score_runs(ins, references, predictions, index=idx)


def test_paired_bootstrap_fixed_clusters_and_reproducibility(tmp_path):
    idx = make_index(tmp_path)
    refs = [ref("1", ids="⿰水木", char="明"), ref("2", ids="⿰水木", char="明"),
            ref("3", ids="⿰水木", char="光"), ref("4", ids="?", char="雨")]
    inputs = [{"sample_id": row["sample_id"]} for row in refs]
    runs = {"a": [pred("1", "⿰水木"), pred("2", "⿰水木"), pred("3", "火"), pred("4", "?")],
            "b": [pred("1", "火"), pred("2", "火"), pred("3", "⿰水木"), pred("4", "木")]}
    first = score_runs(inputs, refs, runs, index=idx, iterations=100, seed=12)
    second = score_runs(inputs, refs, runs, index=idx, iterations=100, seed=12)
    pair = first["paired_differences"]["a - b"]
    assert pair == second["paired_differences"]["a - b"]
    assert pair["seed"] == 12 and pair["iterations"] == 100
    assert "not confidence intervals for true accuracy" in pair["interpretation"]
    for metric in ("eligible_selective_hit", "eligible_selective_upper"):
        result = pair["scores"][metric]
        assert result["paired_image_denominator"] == 3
        assert result["paired_character_denominator"] == 2
        assert result["image_macro"]["difference"] == pytest.approx(1 / 3)
        assert result["character_macro"]["difference"] == 0
        assert result["image_macro"]["valid_replicates"] == 100
    assert not score_runs(inputs, refs, runs, index=idx)["paired_differences"]
    uncertain = score_runs([{"sample_id": "1"}], [ref()],
                           {"a": [pred()], "b": [pred(text=None)]}, index=idx,
                           family_rules=family(), max_states=1, iterations=5, seed=1)
    bounds = uncertain["paired_differences"]["a - b"]["scores"]
    assert bounds["eligible_selective_hit"]["image_macro"]["difference"] == 0
    assert bounds["eligible_selective_upper"]["image_macro"]["difference"] == 1
    empty = score_runs([{"sample_id": "4"}], [refs[-1]],
                       {"a": [pred("4", "?")], "b": [pred("4", "木")]}, index=idx, iterations=5)
    no_refs = empty["paired_differences"]["a - b"]["scores"]["eligible_selective_hit"]
    assert no_refs["paired_image_denominator"] == 0
    assert no_refs["image_macro"]["difference"] is no_refs["image_macro"]["ci95"] is None
    with pytest.raises(ValueError):
        score_runs(inputs, refs, runs, index=idx, iterations=-1)
    a = first["runs"]["a"]["samples"]
    b = first["runs"]["b"]["samples"]
    with pytest.raises(ValueError, match="eligibility"):
        altered = [dict(row) for row in b]
        altered[0]["reference_eligible"] = False
        paired_bootstrap(a, altered, iterations=2, seed=0)


def ranked(texts):
    return {"sample_id": "1", "status": "ok", "candidates": [
        {"rank": i, "text": text} for i, text in enumerate(texts, 1)]}


def test_top_five_cumulative_rank_and_uncertainty(tmp_path):
    idx = make_index(tmp_path)
    reference = ref()
    row = score_sample(reference, ranked(["火", "⿰木", "?", "⿰水火", "⿰氵木", "⿰水⿱日月"]),
                       idx, family())
    assert row["candidate_count"] == 6
    assert row["selective_recall_at_5_candidate_count"] == 5
    assert row["selective_recall_at_5_matched_rank"] == 5
    assert row["scores"]["selective_hit"] is False
    assert row["scores"]["selective_recall_at_5"] is True
    assert row["scores"]["selective_recall_at_5_upper"] is True
    assert row["scores"]["eligible_selective_recall_at_5"] is True
    invalid = score_sample(reference, ranked(["⿰木", "木火"]), idx, family())
    assert invalid["scores"]["selective_recall_at_5"] is False
    assert invalid["scores"]["selective_recall_at_5_upper"] is False
    unknown = score_sample(reference, ranked(["⿰木", "?"]), idx, family())
    assert unknown["selective_recall_at_5_matched_rank"] is None
    assert unknown["scores"]["selective_recall_at_5"] is False
    assert unknown["scores"]["selective_recall_at_5_upper"] is True
    missing = score_sample(reference, pred(text=None), idx, family())
    assert missing["selective_recall_at_5_candidate_count"] == 0
    assert missing["scores"]["selective_recall_at_5_upper"] is False
    one = score_sample(reference, pred(), idx, family())
    assert one["scores"]["selective_recall_at_5"] == one["scores"]["selective_hit"]
    assert one["scores"]["selective_recall_at_5_upper"] == one["scores"]["selective_upper"]
    # A match after the fifth rank is excluded.
    no_match = score_sample(reference, ranked(["火"] * 5 + ["⿰水⿱日月"]), idx, family())
    assert no_match["selective_recall_at_5_matched_rank"] is None
    assert no_match["scores"]["selective_recall_at_5_upper"] is False


def test_top_five_matched_rank_retains_reference_witness(tmp_path):
    idx = make_index(tmp_path)
    row = score_sample(ref(), ranked(["火", "⿰氵木"]), idx, family())
    assert row["selective_recall_at_5_matched_rank"] == 2
    candidate = row["selective_recall_at_5_candidates"][1]
    assert candidate["rank"] == 2
    exhaustive = candidate["comparisons"][0]
    assert exhaustive["reference_ids"] == "⿰水⿱日月"
    assert exhaustive["match"] is False and exhaustive["family_match"] is False
    selective = candidate["selective_comparisons"][0]
    assert selective["reference_ids"] == "⿰水⿱日月"
    assert selective["match"] is True and selective["status"] == "matched"
    assert [step["component"] for step in selective["prediction_trace"]] == ["木"]
    assert selective["indeterminate_reasons"] == ()


def test_top_five_matched_rank_retains_alias_expansion_witness(tmp_path):
    idx = make_index(tmp_path, "U+6C34\t水\t⿱日月\n")
    row = score_sample(ref(ids="⿰⿱日月火"), ranked(["木", "⿰氵火"]), idx, family())
    assert row["selective_recall_at_5_matched_rank"] == 2
    candidate = row["selective_recall_at_5_candidates"][1]
    assert candidate["comparisons"][0]["reference_ids"] == "⿰⿱日月火"
    selective = candidate["selective_comparisons"][0]
    assert selective["match"] is True
    trace = selective["prediction_trace"]
    assert [(step["component"], step.get("alias"), step.get("definition")) for step in trace] == [
        ("氵", "水", None), ("水", None, "⿱日月")]


def test_top_five_bootstrap_fixed_eligible_denominator(tmp_path):
    idx = make_index(tmp_path)
    refs = [ref("1"), ref("2", ids="?")]
    inputs = [{"sample_id": r["sample_id"]} for r in refs]
    a = ranked(["火", "⿰水⿱日月"])
    result = score_runs(inputs, refs, {"a": [a, pred("2", "?")],
                                       "b": [pred("1", "火"), pred("2", "木")]},
                        index=idx, iterations=10, seed=9)
    for run in result["runs"].values():
        assert run["aggregate"]["scores"]["eligible_selective_recall_at_5"]["image_denominator"] == 1
    pair = result["paired_differences"]["a - b"]["scores"]
    for metric in ("eligible_selective_recall_at_5", "eligible_selective_recall_at_5_upper"):
        assert pair[metric]["image_macro"]["difference"] == 1
        assert pair[metric]["image_macro"]["ci95"] == [1, 1]
        assert pair[metric]["paired_image_denominator"] == 1


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_cli_provenance_and_validation(tmp_path):
    dataset, run = tmp_path / "dataset", tmp_path / "run"
    dataset.mkdir(); run.mkdir()
    write_jsonl(dataset / "inputs.jsonl", [{"sample_id": "1"}])
    write_jsonl(dataset / "references.jsonl", [ref()])
    write_jsonl(run / "predictions.jsonl", [pred()])
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    (run / "run.json").write_text(json.dumps({"manifest_sha256": digest(dataset / "inputs.jsonl")}))
    idx = make_index(tmp_path)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"path": "source.tsv", "sha256": digest(tmp_path / "source.tsv"),
                                "provenance": "test", "license": "test"}))
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"policy": "test", "rules": [
        {"components": ["氵", "水"], "contexts": [["H", 0]]}]}), encoding="utf-8")
    output = tmp_path / "out.json"
    command = [sys.executable, "-m", "benchmark.score_selective", "--dataset", str(dataset), "--run", str(run),
               "--source-spec", str(spec), "--family-policy", str(policy), "--max-states", "8", "--output", str(output)]
    subprocess.run(command, check=True, capture_output=True)
    original = output.read_bytes()
    data = json.loads(original)
    assert data["bootstrap_iterations"] == 0 and data["paired_differences"] == {}
    bootstrap_output = tmp_path / "bootstrap.json"
    subprocess.run(command[:-2] + ["--bootstrap-iterations", "--seed", "7", "--output", str(bootstrap_output)],
                   check=True, capture_output=True)
    bootstrap_data = json.loads(bootstrap_output.read_bytes())
    assert bootstrap_data["bootstrap_iterations"] == 2000 and bootstrap_data["bootstrap_seed"] == 7
    provenance = data["provenance"]
    assert data["max_states"] == 8 and data["family_policy"]["sha256"] == digest(policy)
    assert data["index_sha256"] == index_hash(idx) == provenance["index_sha256"]
    assert provenance["source_specs"][0]["sha256"] == digest(spec)
    assert data["sources"]["sources"][0]["sha256"] == digest(tmp_path / "source.tsv")
    assert provenance["inputs_sha256"] == digest(dataset / "inputs.jsonl")
    assert provenance["references_sha256"] == digest(dataset / "references.jsonl")
    assert provenance["prediction_sha256"]["run"] == digest(run / "predictions.jsonl")
    assert provenance["run_manifest_sha256"]["run"] == digest(run / "run.json")
    for key, filename in [("scorer_sha256", "score_selective.py"), ("expansion_scorer_sha256", "score_expansion.py"),
                          ("expansion_sha256", "expansion.py"), ("evaluator_sha256", "ids_evaluator.py"),
                          ("score_helpers_sha256", "score.py")]:
        assert provenance[key] == digest(Path("benchmark") / filename)
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert output.read_bytes() == original
    manifest = digest(dataset / "inputs.jsonl")
    (run / "run.json").write_text(json.dumps({"manifest_sha256": manifest,
                                             "output_predictions_sha256": digest(run / "predictions.jsonl")}))
    declared_output = tmp_path / "declared.json"
    subprocess.run(command[:-1] + [str(declared_output)], check=True, capture_output=True)
    (run / "run.json").write_text(json.dumps({"manifest_sha256": manifest,
                                             "output_predictions_sha256": "bad"}))
    bad_hash = tmp_path / "bad-hash.json"
    mismatch = subprocess.run(command[:-1] + [str(bad_hash)], capture_output=True)
    assert mismatch.returncode != 0 and b"output_predictions_sha256" in mismatch.stderr
    assert not bad_hash.exists()
    (run / "run.json").write_text('{"manifest_sha256":"wrong"}')
    bad = tmp_path / "bad.json"
    assert subprocess.run(command[:-1] + [str(bad)], capture_output=True).returncode != 0
    assert not bad.exists()


@pytest.mark.parametrize(("changed", "message"), [
    ("predictions", "predictions changed during scoring"),
    ("inputs", "dataset manifests changed during scoring"),
    ("references", "dataset manifests changed during scoring"),
    ("run", "run metadata changed during scoring"),
    ("score_selective.py", "source code changed during scoring"),
    ("score_expansion.py", "source code changed during scoring"),
    ("expansion.py", "source code changed during scoring"),
    ("score.py", "source code changed during scoring"),
    ("ids_evaluator.py", "source code changed during scoring"),
])
def test_rejects_inputs_changed_during_scoring(tmp_path, monkeypatch, capsys, changed, message):
    import benchmark.score_selective as scorer

    dataset, run = tmp_path / "dataset", tmp_path / "run"
    dataset.mkdir(); run.mkdir()
    write_jsonl(dataset / "inputs.jsonl", [{"sample_id": "1"}])
    write_jsonl(dataset / "references.jsonl", [ref()])
    predictions = run / "predictions.jsonl"
    write_jsonl(predictions, [pred()])
    manifest = hashlib.sha256((dataset / "inputs.jsonl").read_bytes()).hexdigest()
    (run / "run.json").write_text(json.dumps({"manifest_sha256": manifest}))
    make_index(tmp_path)
    source = tmp_path / "source.tsv"
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"path": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                "provenance": "test", "license": "test"}))
    original_score_runs = scorer.score_runs
    original_sha256 = scorer.sha256
    after_scoring = False

    def checked_sha256(path):
        if after_scoring and Path(path).name == changed:
            return "changed-code-hash"
        return original_sha256(path)

    def change_predictions(*args, **kwargs):
        nonlocal after_scoring
        result = original_score_runs(*args, **kwargs)
        paths = {"predictions": predictions, "inputs": dataset / "inputs.jsonl",
                 "references": dataset / "references.jsonl", "run": run / "run.json"}
        if changed in paths:
            path = paths[changed]
            path.write_bytes(path.read_bytes() + b" ")
        after_scoring = True
        return result

    monkeypatch.setattr(scorer, "sha256", checked_sha256)
    monkeypatch.setattr(scorer, "score_runs", change_predictions)
    output = tmp_path / "out.json"
    with pytest.raises(SystemExit) as error:
        scorer.main(["--dataset", str(dataset), "--run", str(run), "--source-spec", str(spec),
                     "--output", str(output)])
    assert error.value.code == 2
    assert message in capsys.readouterr().err
    assert not output.exists()
