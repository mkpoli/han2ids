import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import unicodedata
from pathlib import Path
from unittest.mock import patch

import benchmark.score as scorer
from benchmark.score import load_policy, paired_bootstrap, score_runs


def ref(sample_id, char="木", ids="木", font="A", **extra):
    return {"sample_id": sample_id, "char": char, "ids": ids, "font": font,
            "review_status": "unreviewed", "source": "synthetic", **extra}


def pred(sample_id, *texts):
    return {"sample_id": sample_id, "status": "ok" if texts else "error",
            "candidates": [{"rank": i, "text": text} for i, text in enumerate(texts, 1)]}


def run(refs, predictions, **kwargs):
    return score_runs([{"sample_id": r["sample_id"]} for r in refs], refs,
                      {"model": predictions}, **kwargs)["runs"]["model"]


class ScoringTests(unittest.TestCase):
    def test_identifier_set_and_duplicate_rows(self):
        inputs = [{"sample_id": "1"}, {"sample_id": "2"}]
        refs = [ref("1"), ref("2")]
        preds = [pred("1", "木"), pred("2", "木")]
        for x, y, z in ((inputs + inputs[:1], refs, preds),
                        (inputs, refs + refs[:1], preds),
                        (inputs, refs, preds + preds[:1]),
                        (inputs, refs[:1], preds),
                        (inputs, refs, preds[:1]),
                        (inputs, refs, preds + [pred("3", "木")])):
            with self.subTest(x=x, y=y, z=z), self.assertRaises(ValueError):
                score_runs(x, y, {"model": z})

    def test_scores_split_by_review_status(self):
        refs = [ref("1", char="甲", review_status="reviewed"),
                ref("2", char="甲", review_status="reviewed", ids="?"),
                ref("3", char="乙")]
        aggregate = run(refs, [pred("1", "木"), pred("2", "?"), pred("3", "火")])["aggregate"]
        subsets = aggregate["per_review_status"]
        self.assertEqual(subsets["reviewed"]["sample_count"], 2)
        self.assertEqual(subsets["reviewed"]["character_count"], 1)
        self.assertEqual(subsets["reviewed"]["scores"]["structural_match"]["image_macro"], 1)
        self.assertEqual(subsets["reviewed"]["scores"]["structural_match"]["image_denominator"], 1)
        self.assertEqual(subsets["reviewed"]["scores"]["raw_exact"]["image_denominator"], 2)
        self.assertEqual(subsets["unreviewed"]["scores"]["structural_match"]["image_macro"], 0)
        self.assertNotIn("per_review_status", subsets["reviewed"])
        self.assertEqual(aggregate["per_font"]["A"]["sample_count"], 3)

    def test_reference_char_is_one_unicode_scalar(self):
        for char in ("", "木火", "木\ufe00", "\ud800", "\udfff"):
            with self.subTest(char=char), self.assertRaises(ValueError):
                run([ref("1", char=char)], [pred("1", "木")])
        self.assertEqual(run([ref("1", char="𠀀")], [pred("1", "木")])["aggregate"]["cluster_count"], 1)

    def test_failures_unscorable_and_all_exact_denominators(self):
        refs = [ref("1"), ref("2", ids="?"), ref("3"), ref("4")]
        scored = run(refs, [pred("1"), pred("2", "?"), pred("3", "?"), pred("4", "⿰木")])
        agg = scored["aggregate"]
        self.assertEqual(agg["scores"]["raw_exact"]["image_macro"], 0.25)
        self.assertEqual(agg["scores"]["raw_exact"]["image_denominator"], 4)
        self.assertEqual(agg["scores"]["structural_match"]["image_denominator"], 3)
        self.assertEqual(agg["scores"]["structural_match"]["image_macro"], 0)
        self.assertEqual(agg["reference_unscorable_samples"], 1)
        self.assertEqual(agg["prediction_status_counts"], {"valid": 0, "invalid": 2, "unsupported": 2})
        self.assertEqual(agg["prediction_run_status_counts"], {"error": 1, "ok": 3})
        self.assertEqual(scored["samples"][1]["scores"]["raw_exact"], 1)
        self.assertIsNone(scored["samples"][1]["scores"]["parseable_exact"])
        self.assertIsNone(scored["samples"][1]["scores"]["parseable_recall_at_5"])
        self.assertEqual(agg["scores"]["parseable_exact"]["image_denominator"], 3)
        self.assertEqual(agg["scores"]["parseable_exact"]["image_macro"], 0)
        self.assertEqual(agg["scores"]["parseable_recall_at_5"]["image_denominator"], 3)

    def test_character_weighting_and_fonts(self):
        refs = [ref("1", char="甲", font="A"), ref("2", char="甲", font="B"),
                ref("3", char="乙", font="A")]
        agg = run(refs, [pred("1", "木"), pred("2", "木"), pred("3", "火")])["aggregate"]
        exact = agg["scores"]["raw_exact"]
        self.assertAlmostEqual(exact["image_macro"], 2 / 3)
        self.assertEqual(exact["character_macro"], .5)
        self.assertEqual(exact["character_denominator"], 2)
        self.assertEqual(agg["per_font"]["A"]["scores"]["raw_exact"]["image_macro"], .5)

    def test_top_five_same_order_and_reviewed_alternatives(self):
        refs = [ref("1", ids="木", review_status="reviewed", reviewed_references=["火"]),
                ref("2")]
        scored = run(refs, [pred("1", "火", "水", "木", "金", "土", "石"),
                            pred("2", "火", "水", "金", "土", "石", "木")])
        a, b = [s["scores"] for s in scored["samples"]]
        self.assertEqual((a["raw_exact"], a["recall_at_5"], a["reference_set_exact"]), (0, 1, 1))
        self.assertEqual((a["parseable_exact"], a["parseable_recall_at_5"]), (0, 1))
        self.assertEqual((b["raw_exact"], b["recall_at_5"]), (0, 0))
        self.assertEqual(a["structural_match"], 1)
        self.assertEqual(a["structural_recall_at_5"], 1)
        self.assertEqual(scored["samples"][0]["candidate_count"], 6)
        bad = ref("x", reviewed_references=["火"])
        with self.assertRaises(ValueError):
            run([bad], [pred("x", "火")])

    def test_tree_reference_cap_and_prediction_cap(self):
        large = "⿰⿱" * 17 + "木" * 35
        refs = [ref("1", ids=large), ref("2")]
        agg = run(refs, [pred("1", large), pred("2", large)])["aggregate"]
        self.assertEqual(agg["scores"]["raw_exact"]["image_macro"], .5)
        self.assertEqual(agg["scores"]["tree_edit_similarity"]["image_denominator"], 1)
        self.assertEqual(agg["scores"]["tree_edit_similarity"]["image_macro"], 0)
        self.assertEqual(agg["tree_reference_status_counts"], {"unsupported": 1, "valid": 1})

    def test_paired_cluster_bootstrap_deterministic(self):
        refs = [ref("1", char="甲"), ref("2", char="甲"), ref("3", char="乙")]
        a = run(refs, [pred("1", "木"), pred("2", "木"), pred("3", "火")])["samples"]
        b = run(refs, [pred("1", "火"), pred("2", "火"), pred("3", "木")])["samples"]
        result = paired_bootstrap(a, b, iterations=300, seed=42)
        self.assertEqual(result, paired_bootstrap(a, b, iterations=300, seed=42))
        exact = result["scores"]["raw_exact"]
        self.assertAlmostEqual(exact["image_macro"]["difference"], 1 / 3)
        self.assertEqual(exact["character_macro"]["difference"], 0)
        self.assertEqual(exact["character_macro"]["ci95"], [-1, 1])

    def test_paired_candidate_depth_comparability(self):
        refs = [ref("1", char="甲"), ref("2", char="乙")]
        inputs = [{"sample_id": r["sample_id"]} for r in refs]
        a = [pred("1", "木", "火", "水", "金", "土"), pred("2", "木")]
        b = [pred("1", "木"), pred("2", "木", "火", "水", "金", "土")]
        result = score_runs(inputs, refs, {"a": a, "b": b}, iterations=10)
        agg = result["runs"]["a"]["aggregate"]
        self.assertEqual(agg["cluster_count"], 2)
        self.assertEqual(agg["candidate_depth"]["at_least_5_samples"], 1)
        pair = result["paired_differences"]["a - b"]
        self.assertEqual(pair["cluster_count"], 2)
        depth = pair["top5_candidate_depth"]
        self.assertEqual(depth["both_at_least_5_samples"], 0)
        self.assertEqual(depth["unequal_depth_samples"], 2)
        self.assertFalse(depth["all_samples_have_five_candidates_in_both_runs"])
        result = score_runs(inputs, refs, {"a": b, "b": b}, iterations=10)
        self.assertEqual(result["paired_differences"]["a - b"]["top5_candidate_depth"]["unequal_depth_samples"], 0)

    def test_policy_scoped_and_documented(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.json"
            path.write_text(json.dumps({"policy": "provisional representation sensitivity",
                "rules": [{"components": ["釒", "金"], "contexts": [["H", 0]]}]}), encoding="utf-8")
            rules, metadata = load_policy(path)
            self.assertEqual(len(metadata["sha256"]), 64)
            refs = [ref("1", ids="⿰金木"), ref("2", ids="⿰木金"), ref("3", ids="⿱水⿰金木")]
            samples = run(refs, [pred("1", "⿰釒木"), pred("2", "⿰木釒"), pred("3", "⿱水⿰釒木")], family_rules=rules)["samples"]
            self.assertEqual([x["scores"]["family_match"] for x in samples], [1, 0, 1])
            self.assertEqual([x["scores"]["structural_match"] for x in samples], [0, 0, 0])
            path.write_text(json.dumps({"policy": "test", "rules": [
                {"components": ["釒", "金", "木"], "contexts": [["H", 0]]}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly two"):
                load_policy(path)
            path.write_text(json.dumps({"policy": "test", "rules": [
                {"components": ["釒", "金"], "positions": [[]]}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "root aliases"):
                load_policy(path)
            path.write_text('{"rules": []}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_policy(path)

    def test_cli_scores_and_hashes_captured_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset, results = root / "dataset", root / "run"
            dataset.mkdir()
            results.mkdir()
            inputs = dataset / "inputs.jsonl"
            references = dataset / "references.jsonl"
            predictions = results / "predictions.jsonl"
            run_file = results / "run.json"
            def jsonl(path, row):
                path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            jsonl(inputs, {"sample_id": "1"})
            jsonl(references, ref("1"))
            jsonl(predictions, pred("1", "木"))
            run_file.write_text(json.dumps({"manifest_sha256": hashlib.sha256(inputs.read_bytes()).hexdigest(),
                                            "checkpoint": "original"}), encoding="utf-8")
            original_hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (inputs, references, predictions, run_file)}
            def mutate_during_score(*args, **kwargs):
                jsonl(inputs, {"sample_id": "changed"})
                jsonl(references, ref("1", ids="火"))
                jsonl(predictions, pred("1", "火"))
                run_file.write_text('{"checkpoint":"changed"}', encoding="utf-8")
                return score_runs(*args, **kwargs)
            output = root / "scores.json"
            with patch.object(scorer, "score_runs", side_effect=mutate_during_score):
                self.assertEqual(scorer.main(["--dataset", str(dataset), "--run", str(results),
                                              "--output", str(output)]), 0)
            result = json.loads(output.read_bytes())
            provenance = result["provenance"]
            self.assertEqual(provenance["inputs_sha256"], original_hashes[inputs])
            self.assertEqual(provenance["references_sha256"], original_hashes[references])
            self.assertEqual(provenance["prediction_sha256"]["run"], original_hashes[predictions])
            self.assertEqual(provenance["run_sha256"]["run"], original_hashes[run_file])
            self.assertEqual(provenance["runs"]["run"]["checkpoint"], "original")
            self.assertEqual(result["runs"]["run"]["aggregate"]["scores"]["raw_exact"]["image_macro"], 1)

    def test_cli_verifies_declared_prediction_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset, results = root / "dataset", root / "run"
            dataset.mkdir()
            results.mkdir()
            def jsonl(path, row):
                path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            inputs = dataset / "inputs.jsonl"
            predictions = results / "predictions.jsonl"
            jsonl(inputs, {"sample_id": "1"})
            jsonl(dataset / "references.jsonl", ref("1"))
            jsonl(predictions, pred("1", "木"))
            metadata = {"manifest_sha256": hashlib.sha256(inputs.read_bytes()).hexdigest(),
                        "output_predictions_sha256": hashlib.sha256(predictions.read_bytes()).hexdigest()}
            (results / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
            command = [sys.executable, "-m", "benchmark.score", "--dataset", str(dataset),
                       "--run", str(results), "--output"]
            output = root / "verified.json"
            subprocess.run(command + [str(output)], check=True, capture_output=True)
            self.assertEqual(json.loads(output.read_bytes())["provenance"]["prediction_sha256"]["run"],
                             metadata["output_predictions_sha256"])
            jsonl(predictions, pred("1", "火"))
            invalid_output = root / "mismatch.json"
            result = subprocess.run(command + [str(invalid_output)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"output_predictions_sha256", result.stderr)
            self.assertFalse(invalid_output.exists())
            metadata["output_predictions_sha256"] = None
            (results / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
            self.assertNotEqual(subprocess.run(command + [str(invalid_output)], capture_output=True).returncode, 0)
            self.assertFalse(invalid_output.exists())

    def test_cli_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset, results = root / "dataset", root / "run"
            dataset.mkdir(); results.mkdir()
            def jsonl(path, rows):
                path.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
            jsonl(dataset / "inputs.jsonl", [{"sample_id": "1"}])
            jsonl(dataset / "references.jsonl", [ref("1")])
            jsonl(results / "predictions.jsonl", [pred("1", "木")])
            (results / "run.json").write_text(json.dumps({"manifest_sha256": hashlib.sha256((dataset / "inputs.jsonl").read_bytes()).hexdigest(), "checkpoint": "example"}), encoding="utf-8")
            output = root / "scores.json"
            command = [sys.executable, "-m", "benchmark.score", "--dataset", str(dataset),
                       "--run", str(results), "--output", str(output)]
            subprocess.run(command, check=True, capture_output=True)
            original = output.read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(original, output.read_bytes())
            scored = json.loads(original)
            self.assertEqual(scored["runs"]["run"]["aggregate"]["sample_count"], 1)
            self.assertEqual(scored["family_status"], "disabled")
            self.assertEqual(scored["runs"]["run"]["aggregate"]["scores"]["family_match"]["image_denominator"], 0)
            self.assertEqual(scored["provenance"]["runs"]["run"]["checkpoint"], "example")
            original_hash = hashlib.sha256((results / "predictions.jsonl").read_bytes()).hexdigest()
            self.assertEqual(scored["provenance"]["prediction_sha256"]["run"], original_hash)
            self.assertTrue(scored["provenance"]["python_version"])
            self.assertEqual(scored["provenance"]["runtime_unicode_database_version"], unicodedata.unidata_version)
            self.assertEqual(scored["provenance"]["evaluator_unicode_version"], "17.0.0")
            jsonl(results / "predictions.jsonl", [pred("1", "火")])
            second = command[:-1] + [str(root / "second.json")]
            subprocess.run(second, check=True, capture_output=True)
            new_score = json.loads((root / "second.json").read_bytes())
            self.assertNotEqual(new_score["provenance"]["prediction_sha256"]["run"], original_hash)
            self.assertEqual(new_score["provenance"]["prediction_sha256"]["run"], hashlib.sha256((results / "predictions.jsonl").read_bytes()).hexdigest())
            (results / "run.json").write_text('{"manifest_sha256":"wrong"}', encoding="utf-8")
            bad = command[:-1] + [str(root / "bad.json")]
            self.assertNotEqual(subprocess.run(bad, capture_output=True).returncode, 0)
            self.assertFalse((root / "bad.json").exists())


if __name__ == "__main__":
    unittest.main()
