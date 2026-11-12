import hashlib
import json
import subprocess
import sys
import unicodedata
import platform

import pytest

from benchmark.expansion import SourceSpec, load_sources
from benchmark.score import load_policy
from benchmark.score_expansion import load_specs, paired_bootstrap, score_runs, score_sample


def ref(sample_id="1", char="明", ids="⿰氵⿰木木", font="A", **kwargs):
    return {"sample_id": sample_id, "char": char, "font": font, "ids": ids,
            "review_status": "reviewed" if "reviewed_references" in kwargs else "unreviewed", **kwargs}


def pred(sample_id="1", text="⿰氵林"):
    return {"sample_id": sample_id, "status": "ok" if text is not None else "error",
            "candidates": [] if text is None else [{"rank": 1, "text": text}]}


def index(tmp_path, text="U+6797\t林\t⿰木木\n"):
    path = tmp_path / "source.tsv"
    path.write_text(text, encoding="utf-8")
    return load_sources([SourceSpec(path, hashlib.sha256(path.read_bytes()).hexdigest(), "fixture", "test")])


def test_expansion_and_no_implicit_aliases(tmp_path):
    idx = index(tmp_path)
    sample = score_sample(ref(), pred(), idx)
    assert sample["expansion_status"] == "match"
    assert sample["scores"]["strict_hit"] is False
    assert sample["scores"]["added_hit"] is sample["scores"]["relaxed_hit"] is True
    assert sample["comparisons"][0]["reference_ids"] == "⿰氵⿰木木"
    assert sample["comparisons"][0]["reference"]["status"] == "ok"
    assert sample["comparisons"][0]["prediction"]["trace"][0]["component"] == "林"
    alias = score_sample(ref(ids="⿰金木"), pred(text="⿰釒木"), idx)
    assert alias["expansion_status"] == "no_match"
    assert alias["scores"]["relaxed_hit"] is False


def test_policy_combines_family_and_expansion_monotonically(tmp_path):
    idx = index(tmp_path)
    policy = tmp_path / "family.json"
    policy.write_text(json.dumps({"policy": "test contextual policy", "rules": [
        {"components": ["釒", "金"], "contexts": [["H", 0]]}]}), encoding="utf-8")
    rules, _ = load_policy(policy)
    reference = ref(ids="⿰金⿰木木")
    prediction = pred(text="⿰釒林")
    disabled = score_sample(reference, prediction, idx)
    assert disabled["scores"]["family_only_hit"] is None
    assert disabled["scores"]["combined_hit"] is None
    enabled = score_sample(reference, prediction, idx, rules)
    scores = enabled["scores"]
    assert scores["strict_hit"] is scores["family_only_hit"] is scores["relaxed_hit"] is False
    assert scores["combined_hit"] is scores["combined_upper"] is True
    assert enabled["comparisons"][0]["match"] is False
    assert enabled["comparisons"][0]["family_match"] is True
    # Family and expansion scores remain separate and feed the cumulative union.
    cases = [("⿰金木", "⿰釒木"), ("⿰金⿰木木", "⿰金林"),
             ("⿰金木", "⿰金木"), ("⿰金⿰木木", "⿰釒林")]
    for expected, text in cases:
        scores = score_sample(ref(ids=expected), pred(text=text), idx, rules)["scores"]
        assert scores["strict_hit"] <= scores["family_only_hit"] <= scores["combined_hit"]
        assert scores["strict_hit"] <= scores["relaxed_hit"] <= scores["combined_hit"]
        assert scores["family_only_hit"] <= scores["family_only_upper"] <= scores["combined_upper"]
        assert scores["relaxed_hit"] <= scores["relaxed_upper"] <= scores["combined_upper"]
    # The same family components are not aliased in an unapproved position.
    assert not score_sample(ref(ids="⿰木金"), pred(text="⿰木釒"), idx, rules)["scores"]["combined_hit"]


def test_policy_bounds_and_paired_reference_denominators(tmp_path):
    idx = index(tmp_path, "U+7532\t甲\t⿰乙木\nU+4E59\t乙\t⿱甲日\n")
    policy = tmp_path / "family.json"
    policy.write_text(json.dumps({"policy": "test", "rules": [
        {"components": ["釒", "金"], "contexts": [["H", 0]]}]}), encoding="utf-8")
    rules, _ = load_policy(policy)
    refs = [ref("1", ids="⿰甲木"), ref("2", ids="⿰金木"), ref("3", ids="?")]
    inputs = [{"sample_id": r["sample_id"]} for r in refs]
    output = score_runs(inputs, refs, {"a": [pred("1", "⿰火木"), pred("2", "⿰釒木"), pred("3", "?")],
                                      "b": [pred("1", None), pred("2", "⿰火木"), pred("3", "火")]},
                        index=idx, family_rules=rules, iterations=20)
    a = output["runs"]["a"]
    assert a["samples"][0]["scores"]["combined_hit"] is False
    assert a["samples"][0]["scores"]["combined_upper"] is True
    assert a["samples"][1]["scores"]["family_only_hit"] is True
    assert a["samples"][1]["scores"]["combined_hit"] is True
    mixed = score_sample(ref(ids="⿰甲木", reviewed_references=["⿰金⿰木木"]),
                         pred(text="⿰釒林"), index(tmp_path, "U+7532\t甲\t⿰乙木\nU+4E59\t乙\t⿱甲日\nU+6797\t林\t⿰木木\n"), rules)
    assert [c["family_match"] for c in mixed["comparisons"]] == [None, True]
    assert mixed["scores"]["combined_hit"] is True
    for metric in ("eligible_strict_hit", "eligible_family_only_hit", "eligible_relaxed_hit", "eligible_combined_hit"):
        assert a["aggregate"]["scores"][metric]["image_denominator"] == 2
        assert output["paired_differences"]["a - b"]["scores"][metric]["paired_image_denominator"] == 2
    disabled = score_runs(inputs, refs, {"a": [pred("1", None), pred("2", None), pred("3", None)]}, index=idx)
    assert disabled["family_status"] == "disabled"
    assert disabled["runs"]["a"]["aggregate"]["scores"]["combined_hit"]["image_denominator"] == 0


def test_indeterminate_and_any_reference_match(tmp_path):
    idx = index(tmp_path, "U+7532\t甲\t⿰乙木\nU+4E59\t乙\t⿱甲日\n")
    reference = ref(ids="⿰甲木", reviewed_references=["⿰火木"])
    sample = score_sample(reference, pred(text="⿰火木"), idx)
    assert [x["match"] for x in sample["comparisons"]] == [None, True]
    assert sample["comparisons"][0]["reference"]["status"] == "cycle"
    assert sample["expansion_status"] == "match"
    # A matching expanded alternative wins even when an earlier reference fails.
    idx = index(tmp_path, "U+7532\t甲\t⿰乙木\nU+4E59\t乙\t⿱甲日\nU+6797\t林\t⿰木木\n")
    reference = ref(ids="⿰甲木", reviewed_references=["⿰氵⿰木木"])
    sample = score_sample(reference, pred(text="⿰氵林"), idx)
    assert [item["match"] for item in sample["comparisons"]] == [None, True]
    assert sample["scores"]["strict_hit"] is False
    assert sample["scores"]["added_hit"] is True
    reference = ref(ids="⿰甲木", reviewed_references=["⿰水木"])
    sample = score_sample(reference, pred(text="⿰火木"), idx)
    assert [x["match"] for x in sample["comparisons"]] == [None, False]
    assert sample["expansion_status"] == "indeterminate"
    assert sample["scores"]["eligible_relaxed_hit"] is False
    assert sample["scores"]["eligible_relaxed_upper"] is True
    # Reviewed references cannot be attached to unreviewed images.
    reference["review_status"] = "unreviewed"
    with pytest.raises(ValueError, match="review_status"):
        score_sample(reference, pred(text="⿰火木"), idx)


def test_baseline_survives_cycle_target_block_and_invalid_raw(tmp_path):
    idx = index(tmp_path, "U+7532\t甲\t⿰乙木\nU+4E59\t乙\t⿱甲日\n")
    for reference, text, status in [(ref(ids="⿰甲木"), "⿰甲木", "cycle"),
                                    (ref(ids="⿰明木"), "⿰明木", "target_blocked"),
                                    (ref(ids="?"), "?", "parse_unsupported")]:
        sample = score_sample(reference, pred(text=text), idx)
        assert sample["comparisons"][0]["prediction"]["status"] == status
        assert sample["expansion_status"] == "indeterminate"
        assert sample["scores"]["strict_hit"] is sample["scores"]["relaxed_hit"] is True
        assert sample["scores"]["added_hit"] is False
    # Normalized structural equality is preserved even if expansion fails.
    sample = score_sample(ref(ids="⿲甲木火"), pred(text="⿰⿰甲木火"), idx)
    assert sample["scores"]["structural_match"] is True
    assert sample["scores"]["relaxed_hit"] is True


def test_invalid_prediction_upper_bounds_and_unsupported(tmp_path):
    idx = index(tmp_path)
    policy = tmp_path / "family.json"
    policy.write_text(json.dumps({"policy": "test", "rules": [
        {"components": ["釒", "金"], "contexts": [["H", 0]]}]}), encoding="utf-8")
    rules, _ = load_policy(policy)
    reference = ref(ids="⿰金木", reviewed_references=["⿰甲木", "?"])
    for text in ("", "⿰木", "木火"):
        for family in (None, rules):
            sample = score_sample(reference, pred(text=text), idx, family)
            assert sample["prediction_status"] == "invalid"
            assert sample["comparisons"][0]["prediction"]["status"] == "parse_invalid"
            assert sample["expansion_status"] == "invalid_prediction"
            assert sample["scores"]["relaxed_hit"] is False
            assert sample["scores"]["relaxed_upper"] is False
            if family is not None:
                assert sample["scores"]["family_only_upper"] is False
                assert sample["scores"]["combined_upper"] is False
    for family in (None, rules):
        sample = score_sample(reference, pred(text="⿰?木"), idx, family)
        assert sample["prediction_status"] == "unsupported"
        assert sample["scores"]["relaxed_hit"] is False
        assert sample["scores"]["relaxed_upper"] is True
        if family is not None:
            assert sample["scores"]["family_only_upper"] is True
            assert sample["scores"]["combined_upper"] is True
    # Raw exact hits are cumulative even for malformed reference strings.
    sample = score_sample(ref(ids="⿰木"), pred(text="⿰木"), idx, rules)
    assert sample["scores"]["strict_hit"] is True
    assert sample["scores"]["relaxed_upper"] is True
    assert sample["scores"]["combined_upper"] is True


def test_errors_aggregation_and_fixed_paired_denominator(tmp_path):
    idx = index(tmp_path, "U+7532\t甲\t⿰乙木\nU+4E59\t乙\t⿱甲日\n")
    refs = [ref("1", char="明", ids="⿰甲木", font="A"),
            ref("2", char="明", ids="⿰火木", font="B"),
            ref("3", char="光", ids="?", font="A")]
    inputs = [{"sample_id": row["sample_id"]} for row in refs]
    result = score_runs(inputs, refs, {"a": [pred("1", "⿰火木"), pred("2", None), pred("3", "?")],
                                        "b": [pred("1", "⿰水木"), pred("2", "⿰火木"), pred("3", "火")]},
                        index=idx, iterations=50, seed=2)
    samples = result["runs"]["a"]["samples"]
    assert samples[1]["expansion_status"] == "no_prediction"
    assert samples[1]["scores"]["relaxed_hit"] is False
    agg = result["runs"]["a"]["aggregate"]
    assert agg["reference_eligible_samples"] == 2
    assert agg["unscorable_expansion"] == 2
    assert agg["scores"]["eligible_relaxed_hit"]["image_denominator"] == 2
    assert agg["scores"]["eligible_relaxed_hit"]["image_macro"] == 0
    assert agg["scores"]["eligible_relaxed_upper"]["image_macro"] == .5
    assert agg["per_font"]["A"]["scores"]["raw_exact"]["character_macro"] == .5
    pair = result["paired_differences"]["a - b"]
    assert pair["scores"]["eligible_relaxed_hit"]["paired_image_denominator"] == 2
    assert pair["scores"]["eligible_relaxed_hit"]["image_macro"]["difference"] == -.5
    assert pair == paired_bootstrap(result["runs"]["a"]["samples"], result["runs"]["b"]["samples"], iterations=50, seed=2)


def test_id_candidate_and_target_validation(tmp_path):
    idx = index(tmp_path)
    inputs = [{"sample_id": "1"}]
    for ins, refs, runs in [(inputs + inputs, [ref()], {"a": [pred()]}),
                            (inputs, [ref(), ref()], {"a": [pred()]}),
                            (inputs, [ref()], {"a": [pred(), pred()]}),
                            (inputs, [ref()], {"a": [pred("2")]}),
                            (inputs, [ref("2")], {"a": [pred()]})]:
        with pytest.raises(ValueError):
            score_runs(ins, refs, runs, index=idx)
    with pytest.raises(ValueError, match="Unicode scalar"):
        score_sample(ref(char="明日"), pred(text=None), idx)
    with pytest.raises(ValueError, match="ranked candidate"):
        score_sample(ref(), {"sample_id": "1", "status": "ok", "candidates": [{"rank": 2, "text": "木"}]}, idx)


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_source_spec_and_cli_provenance(tmp_path):
    dataset, run = tmp_path / "dataset", tmp_path / "run"
    dataset.mkdir(); run.mkdir()
    write_jsonl(dataset / "inputs.jsonl", [{"sample_id": "1"}])
    write_jsonl(dataset / "references.jsonl", [ref()])
    write_jsonl(run / "predictions.jsonl", [pred()])
    manifest = hashlib.sha256((dataset / "inputs.jsonl").read_bytes()).hexdigest()
    (run / "run.json").write_text(json.dumps({"manifest_sha256": manifest, "checkpoint": "test"}))
    source = tmp_path / "source.tsv"
    source.write_text("U+6797\t林\t⿰木木\n", encoding="utf-8")
    spec = tmp_path / "spec.json"
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    metadata = {"path": source.name, "sha256": source_sha, "provenance": "pinned revision", "license": "test"}
    spec.write_text(json.dumps(metadata), encoding="utf-8")
    output = tmp_path / "out.json"
    command = [sys.executable, "-m", "benchmark.score_expansion", "--dataset", str(dataset), "--run", str(run),
               "--source-spec", str(spec), "--output", str(output)]
    subprocess.run(command, check=True, capture_output=True)
    original = output.read_bytes()
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert output.read_bytes() == original
    data = json.loads(original)
    assert data["sources"]["sources"][0]["sha256"] == source_sha
    assert data["sources"]["sources"][0]["license"] == "test"
    assert data["provenance"]["inputs_sha256"] == manifest
    assert data["provenance"]["prediction_sha256"]["run"] == hashlib.sha256((run / "predictions.jsonl").read_bytes()).hexdigest()
    assert data["provenance"]["python_version"] == platform.python_version()
    assert data["provenance"]["unicode_version"] == unicodedata.unidata_version
    assert data["provenance"]["runs"]["run"]["checkpoint"] == "test"
    assert data["provenance"]["source_specs"][0]["sha256"] == hashlib.sha256(spec.read_bytes()).hexdigest()
    assert data["family_status"] == "disabled" and data["family_policy"] is None
    policy = tmp_path / "family.json"
    policy.write_text(json.dumps({"policy": "test policy", "rules": [
        {"components": ["釒", "金"], "contexts": [["H", 0]]}]}), encoding="utf-8")
    policy_output = tmp_path / "policy-out.json"
    subprocess.run(command[:-1] + [str(policy_output), "--family-policy", str(policy)], check=True, capture_output=True)
    with_policy = json.loads(policy_output.read_bytes())
    assert with_policy["family_status"] == "enabled"
    assert with_policy["family_policy"]["document"]["policy"] == "test policy"
    assert with_policy["family_policy"]["sha256"] == hashlib.sha256(policy.read_bytes()).hexdigest()
    (run / "run.json").write_text('{"manifest_sha256":"wrong"}')
    bad_output = tmp_path / "bad.json"
    bad = subprocess.run(command[:-1] + [str(bad_output)], capture_output=True)
    assert bad.returncode != 0 and not bad_output.exists()
    for key, value in [("sha256", "0" * 64), ("provenance", ""), ("license", "")]:
        spec.write_text(json.dumps({**metadata, key: value}), encoding="utf-8")
        with pytest.raises(ValueError):
            load_specs([spec])
