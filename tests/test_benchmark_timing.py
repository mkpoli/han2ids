import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from benchmark import timing


def make_args(tmp_path, **overrides):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    image = dataset / "sample.png"
    Image.new("L", (4, 4), 255).save(image)
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    rows = [{"sample_id": f"id-{i}", "image": "sample.png", "image_sha256": digest} for i in range(3)]
    (dataset / "inputs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    # Any accidental attempt to open labels fails.
    (dataset / "references.jsonl").mkdir()
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"model")
    settings = dict(dataset=dataset, output=tmp_path / "result", system="han2ids", checkpoint=checkpoint,
                    app=None, device="cpu", gpu_index=0, cuda_memory_fraction=None, threads=2,
                    batch_size=2, limit=None, decode="greedy-batched", no_tta=True, warmup=3, repeats=2)
    settings.update(overrides)
    return SimpleNamespace(**settings)


class Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        self.value += 100
        return self.value


class Adapter:
    def __init__(self, args):
        self.device = args.device
        self.calls = []

    def predict(self, images):
        self.calls.append(len(images))
        return [[{"text": "木", "score": 0.5}] for _ in images]

    def execution(self):
        return {"device": self.device, "warnings": []}


def test_quantiles_and_synchronization_order():
    assert timing.quantile([100, 200, 300, 400], .5) == 250
    assert timing.quantile([100, 200, 300, 400], .95) == 385
    events = []
    values = iter([100, 140])
    def sync(device):
        events.append(("sync", device))
    def clock():
        events.append("clock")
        return next(values)
    result, elapsed = timing.timed_call(lambda: events.append("predict") or 42, "cuda:0", clock, sync)
    assert result == 42 and elapsed == 40
    assert events == [("sync", "cuda:0"), "clock", "predict", ("sync", "cuda:0"), "clock"]


def test_real_sync_dispatches_cuda(monkeypatch):
    import sys
    events = []
    fake = SimpleNamespace(cuda=SimpleNamespace(synchronize=lambda device: events.append(device)))
    monkeypatch.setitem(sys.modules, "torch", fake)
    timing.synchronize("cuda:2")
    timing.synchronize("cpu")
    assert events == ["cuda:2"]


def test_full_run_preselected_scenarios_and_predictions(tmp_path, monkeypatch):
    args = make_args(tmp_path)
    monkeypatch.setattr(timing, "torch_settings", lambda adapter: {"precision_policy": "fake"})
    adapters, syncs = [], []
    def factory(args):
        adapters.append(Adapter(args))
        return adapters[-1]
    report = timing.run(args, factory, Clock(), syncs.append)
    assert report["status"] == "ok" and report["fallback"] is False
    assert report["input_ids"] == ["id-0", "id-1", "id-2"]
    assert report["cold_load_ns"] == 100
    assert adapters[0].calls == [1] * 15 + [2, 1] * 5
    assert syncs == ["cpu"] * (2 + 2 * 25)
    one, many = report["scenarios"]["interactive"], report["scenarios"]["throughput"]
    assert one["inputs"] == many["inputs"] == 6
    assert one["batch_sizes"] == [1] * 6 and many["batch_sizes"] == [2, 1] * 2
    assert one["total_elapsed_ns"] == 600 and many["total_elapsed_ns"] == 400
    assert one["p95_batch_ns"] == 100 and one["inputs_per_second"] == 10_000_000
    for scenario in (one, many):
        for item in scenario["passes"]:
            path = args.output / item["predictions"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item["predictions_sha256"]
            metadata = json.loads((args.output / item["run"] / "run.json").read_text())
            assert metadata["manifest_sha256"] == report["manifest_sha256"]
            assert metadata["output_predictions_sha256"] == item["predictions_sha256"]
            assert metadata["settings"]["batch_size"] == scenario["batch_size"]
            assert metadata["initial_execution"] == report["actual_execution"]
            records = [json.loads(line) for line in path.read_text().splitlines()]
            assert [r["sample_id"] for r in records] == report["input_ids"]
            assert all(r["status"] == "ok" and r["candidates"][0]["rank"] == 1 for r in records)
    assert json.loads((args.output / "timing.json").read_text())["status"] == "ok"


@pytest.mark.parametrize("limit", [None, 2])
def test_predictions_are_scored_as_run_directories(tmp_path, monkeypatch, limit):
    from benchmark import score

    args = make_args(tmp_path, limit=limit)
    monkeypatch.setattr(timing, "torch_settings", lambda adapter: {})
    report = timing.run(args, Adapter, Clock(), lambda device: None)
    selected = (args.output / "selected-inputs.jsonl").read_bytes()
    assert hashlib.sha256(selected).hexdigest() == report["manifest_sha256"]
    source = (args.dataset / "inputs.jsonl").read_bytes()
    assert report["source_manifest_sha256"] == hashlib.sha256(source).hexdigest()
    if limit is not None:
        assert report["manifest_sha256"] != report["source_manifest_sha256"]
    else:
        assert selected == source
    dataset = tmp_path / "scoring-dataset"
    dataset.mkdir()
    (dataset / "inputs.jsonl").write_bytes(selected)
    references = [{"sample_id": sample_id, "char": "木", "font": "test",
                   "ids": "木", "review_status": "reviewed"} for sample_id in report["input_ids"]]
    (dataset / "references.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in references))
    score_path = tmp_path / "score.json"
    assert score.main(["--dataset", str(dataset), "--run", str(args.output / "interactive-pass-1"),
                       "--run", str(args.output / "throughput-pass-1"), "--output", str(score_path),
                       "--bootstrap-iterations", "1"]) == 0
    result = json.loads(score_path.read_text())
    assert set(result["runs"]) == {"interactive-pass-1", "throughput-pass-1"}
    assert result["provenance"]["inputs_sha256"] == report["manifest_sha256"]


def test_image_hash_failure_is_recorded_before_adapter_load(tmp_path):
    args = make_args(tmp_path)
    (args.dataset / "sample.png").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        timing.run(args, lambda args: pytest.fail("adapter must not load"), Clock(), lambda device: None)
    report = json.loads((args.output / "timing.json").read_text())
    assert report["status"] == "error" and "SHA-256 mismatch" in report["error"]
    assert not list(args.output.glob("*.jsonl"))


@pytest.mark.parametrize("failure", ["partial", "empty", "nan", "fallback", "exception"])
def test_bad_outputs_and_fallback_fail_without_partial_results(tmp_path, monkeypatch, failure):
    args = make_args(tmp_path)
    monkeypatch.setattr(timing, "torch_settings", lambda adapter: {})
    class Bad(Adapter):
        def predict(self, images):
            if failure == "partial":
                return []
            if failure == "empty":
                return [[] for _ in images]
            if failure == "nan":
                return [[{"text": "木", "score": float("nan")}] for _ in images]
            if failure == "fallback":
                self.device = "cuda:0"
                return super().predict(images)
            raise RuntimeError("inference failed")
    with pytest.raises((RuntimeError, ValueError)):
        timing.run(args, Bad, Clock(), lambda device: None)
    report = json.loads((args.output / "timing.json").read_text())
    assert report["status"] == "error" and report["error"] and not report["scenarios"]
    assert report["fallback"] is (True if failure == "fallback" else False)
    assert not list(args.output.glob("*.jsonl"))


def test_requested_device_mismatch_and_warning_are_errors(tmp_path, monkeypatch):
    args = make_args(tmp_path, device="cuda")
    class Fallback(Adapter):
        def __init__(self, args):
            self.device = "cpu"
    with pytest.raises(RuntimeError, match="fallback"):
        timing.run(args, Fallback, Clock(), lambda device: None)
    report = json.loads((args.output / "timing.json").read_text())
    assert report["fallback"] is True and report["actual_execution"]["device"] == "cpu"


def test_cuda_synchronization_surrounds_load_and_every_batch(tmp_path, monkeypatch):
    args = make_args(tmp_path, device="cuda")
    monkeypatch.setattr(timing, "torch_settings", lambda adapter: {})
    class CudaAdapter(Adapter):
        def __init__(self, args):
            super().__init__(args)
            self.device = "cuda:0"
    syncs = []
    report = timing.run(args, CudaAdapter, Clock(), syncs.append)
    assert report["actual_execution"]["device"] == "cuda:0"
    assert syncs == ["cuda:0"] * 52


def test_failure_in_second_scenario_does_not_publish_partial_passes(tmp_path, monkeypatch):
    args = make_args(tmp_path)
    monkeypatch.setattr(timing, "torch_settings", lambda adapter: {})
    class BadBatch(Adapter):
        def predict(self, images):
            if len(images) > 1:
                raise RuntimeError("batch failed")
            return super().predict(images)
    with pytest.raises(RuntimeError, match="batch failed"):
        timing.run(args, BadBatch, Clock(), lambda device: None)
    assert not list(args.output.glob("*.jsonl"))
    assert json.loads((args.output / "timing.json").read_text())["scenarios"] == {}


def test_validation_rejects_short_runs(tmp_path):
    args = make_args(tmp_path, warmup=2)
    with pytest.raises(ValueError, match="warmup"):
        timing.run(args)
    args.warmup = 3
    args.repeats = 1
    with pytest.raises(ValueError, match="repeats"):
        timing.run(args)
