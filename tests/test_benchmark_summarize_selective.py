import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from benchmark.expansion import SourceSpec, load_sources
from benchmark.export import _validate_score
from benchmark.score_selective import score_runs
from benchmark.summarize_selective import summarize


def make_report(tmp_path):
    source = tmp_path / "source.tsv"
    source.write_text("U+9F98\t龘\t⿱龜龍\nU+9EA4\t麤\t⿱龜龍\n", encoding="utf-8")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    idx = load_sources([SourceSpec(source, sha, "pinned external source", "GPL-2.0-or-later")])
    inputs = [{"sample_id": "sample-1"}]
    refs = [{"sample_id": "sample-1", "ids": "⿰月日", "char": "明", "font": "A", "review_status": "unreviewed"}]
    def prediction(text):
        return [{"sample_id": "sample-1", "status": "ok", "candidates": [{"rank": 1, "text": text}]}]
    report = score_runs(inputs, refs, {"a": prediction("⿰火水"), "b": prediction("⿰龘木")},
                        index=idx, iterations=10, seed=3)
    assert report["sources"]["single_definition_collisions"]["examples"]
    report["family_policy"] = {"sha256": "policy-hash", "document": {"policy": "frozen policy", "rules": [
        {"components": ["氵", "水"], "contexts": [["H", 0]], "unused": "⿱龜龍"}]}}
    report["family_status"] = "enabled"
    report["provenance"] = {"inputs_sha256": "input-hash", "references_sha256": "refs-hash",
                            "scorer_sha256": "scorer-hash", "expansion_scorer_sha256": "base-hash",
                            "expansion_sha256": "expansion-hash", "score_helpers_sha256": "helper-hash",
                            "evaluator_sha256": "evaluator-hash", "index_sha256": report["index_sha256"],
                            "source_specs": [{"name": "spec.json", "sha256": "spec-hash"}],
                            "prediction_sha256": {"a": "pred-a", "b": "pred-b"},
                            "run_manifest_sha256": {"a": "run-a", "b": "run-b"},
                            "runs": {"a": {"prompt": "⿱龜龍"}, "b": {"text": "⿰火水"}}}
    return report


def test_sanitized_report_retains_scores_and_hashes(tmp_path):
    report = make_report(tmp_path)
    result = summarize(report, "original-score-hash")
    text = json.dumps(result, ensure_ascii=False)
    for forbidden in ("⿱龜龍", "龘", "麤", "⿰火水", "⿰月日", "⿰龘木", "prediction_trace",
                      "reference_trace", '"comparisons"', "representative_ids"):
        assert forbidden not in text
    assert result["sources"]["counts"] == report["sources"]["counts"]
    source = result["sources"]["sources"][0]
    assert source["sha256"] == report["sources"]["sources"][0]["sha256"]
    assert source["license"] == "GPL-2.0-or-later"
    collisions = result["sources"]["single_definition_collisions"]
    assert collisions["class_count"] == 1 and collisions["character_count"] == 2
    assert "examples" not in collisions
    assert result["family_policy"]["sha256"] == "policy-hash"
    assert result["family_policy"]["document"]["rules"][0] == {"components": ["氵", "水"], "contexts": [["H", 0]]}
    assert result["paired_differences"] == report["paired_differences"]
    paired_scores = result["paired_differences"]["a - b"]["scores"]
    assert "eligible_selective_recall_at_5" in paired_scores
    assert "eligible_selective_recall_at_5_upper" in paired_scores
    for name in ("a", "b"):
        assert result["runs"][name]["aggregate"] == report["runs"][name]["aggregate"]
        sample = result["runs"][name]["samples"][0]
        assert sample["sample_id"] == "sample-1" and sample["scores"] == report["runs"][name]["samples"][0]["scores"]
        assert sample["selective_status"] == report["runs"][name]["samples"][0]["selective_status"]
        assert sample["selective_recall_at_5_candidate_count"] == 1
        assert "selective_recall_at_5_candidates" not in sample
        assert sample["selective_recall_at_5_matched_rank"] == report["runs"][name]["samples"][0]["selective_recall_at_5_matched_rank"]
    p = result["provenance"]
    assert p["source_selective_sha256"] == "original-score-hash"
    assert p["scorer_sha256"] == "scorer-hash" and p["evaluator_sha256"] == "evaluator-hash"
    assert p["run_manifest_sha256"] == {"a": "run-a", "b": "run-b"} and "runs" not in p
    assert p["summarizer_sha256"] == hashlib.sha256(Path("benchmark/summarize_selective.py").read_bytes()).hexdigest()
    summary_file = tmp_path / "summary.json"
    summary_file.write_text(json.dumps(result))
    assert _validate_score(summary_file, "input-hash", "refs-hash", {"a": "pred-a", "b": "pred-b"})


def test_cli_hashes_original_bytes_and_does_not_clobber(tmp_path):
    report = make_report(tmp_path)
    source, output = tmp_path / "scores.json", tmp_path / "summary.json"
    source.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    original = source.read_bytes()
    command = [sys.executable, "-m", "benchmark.summarize_selective", "--score", str(source), "--output", str(output)]
    subprocess.run(command, check=True, capture_output=True)
    result = json.loads(output.read_text())
    assert result["provenance"]["source_selective_sha256"] == hashlib.sha256(original).hexdigest()
    saved = output.read_bytes()
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert output.read_bytes() == saved and source.read_bytes() == original
    report["format"] = "other"
    source.write_text(json.dumps(report))
    bad = tmp_path / "bad.json"
    assert subprocess.run(command[:-1] + [str(bad)], capture_output=True).returncode != 0
    assert not bad.exists()


def test_rejects_invalid_scores_and_run_hashes(tmp_path):
    report = make_report(tmp_path)
    report["runs"]["a"]["samples"][0]["scores"]["injected"] = "⿱龜龍"
    with pytest.raises(ValueError, match="numeric"):
        summarize(report, "hash")
    report = make_report(tmp_path)
    report["provenance"]["prediction_sha256"].pop("a")
    with pytest.raises(ValueError, match="prediction hashes"):
        summarize(report, "hash")
