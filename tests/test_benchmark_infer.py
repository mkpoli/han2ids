import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
from PIL import Image


SPEC = importlib.util.spec_from_file_location("benchmark_infer", Path(__file__).parents[1] / "benchmark" / "infer.py")
infer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(infer)


def make_dataset(tmp_path):
    root = tmp_path / "dataset"
    root.mkdir()
    image = root / "image.png"
    Image.new("L", (8, 8), "white").save(image)
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    return root, {"sample_id": "opaque-1", "image": "image.png", "image_sha256": digest}


def manifest(root, rows):
    (root / "inputs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))


def args_for(tmp_path, root, **kwargs):
    checkpoint = tmp_path / "trusted.pt"
    checkpoint.write_bytes(b"checkpoint")
    values = dict(dataset=root, system="han2ids", checkpoint=checkpoint, app=None,
                  output=tmp_path / "out", device="cpu", gpu_index=0, threads=4,
                  batch_size=2, limit=None, decode="greedy", no_tta=False,
                  cuda_memory_fraction=None)
    values.update(kwargs)
    return types.SimpleNamespace(**values)


class FakeAdapter:
    def __init__(self, args):
        self.device = "cuda:0"
        self.warnings = []
        self.received = []

    def predict(self, images):
        self.received.extend(image.size for image in images)
        self.device = "cpu"
        self.warnings.append("GPU fallback")
        return [[{"text": "⿱宀子", "score": 0.9, "raw_ids": ["⿱宀子"]},
                 {"text": "⿰木木", "score": 0.8}] for image in images]

    def execution(self):
        return {"device": self.device, "warnings": list(self.warnings)}


def records(out):
    return [json.loads(line) for line in (out / "predictions.jsonl").read_text().splitlines()]


def test_run_preserves_rank_and_errors_and_fallback(tmp_path):
    root, row = make_dataset(tmp_path)
    bad = {**row, "sample_id": "bad-hash", "image_sha256": "0" * 64}
    manifest(root, [row, bad])
    # The runner must not attempt to read reference material.
    (root / "references.jsonl").mkdir()
    args = args_for(tmp_path, root)
    result = infer.run(args, FakeAdapter)
    a, b = records(args.output)
    assert a["status"] == "ok" and [c["rank"] for c in a["candidates"]] == [1, 2]
    assert a["candidates"][0]["text"] == "⿱宀子"
    assert a["candidates"][0]["raw_ids"] == ["⿱宀子"]
    assert b["status"] == "error" and "SHA-256 mismatch" in b["error"]
    assert result["initial_execution"]["device"] == "cuda:0"
    assert result["final_execution"] == {"device": "cpu", "warnings": ["GPU fallback"]}
    metadata = json.loads((args.output / "run.json").read_text())
    assert metadata["settings"]["concurrency"] == "single-process, serial batches"
    assert metadata["manifest_sha256"] and metadata["files_sha256"]


def test_manifest_rejects_duplicates_and_extra_fields(tmp_path):
    root, row = make_dataset(tmp_path)
    manifest(root, [row, row])
    with pytest.raises(ValueError, match="duplicate"):
        infer.load_manifest(root)
    manifest(root, [{**row, "gold": "secret"}])
    with pytest.raises(ValueError, match="expected only"):
        infer.load_manifest(root)


@pytest.mark.parametrize("image", ["../outside.png", "/etc/passwd", "escape.png", "missing.png"])
def test_invalid_image_paths_are_per_sample_errors(tmp_path, image):
    root, row = make_dataset(tmp_path)
    (root / "escape.png").symlink_to(tmp_path / "outside.png")
    (tmp_path / "outside.png").write_bytes(b"outside")
    manifest(root, [{**row, "image": image}])
    args = args_for(tmp_path, root)
    infer.run(args, FakeAdapter)
    assert records(args.output)[0]["status"] == "error"


def test_bad_images_model_errors_and_limit(tmp_path):
    root, row = make_dataset(tmp_path)
    invalid = root / "bad.png"
    invalid.write_bytes(b"not an image")
    manifest(root, [{**row, "sample_id": "bad", "image": "bad.png",
                     "image_sha256": hashlib.sha256(invalid.read_bytes()).hexdigest()}, row])
    args = args_for(tmp_path, root, limit=1)
    infer.run(args, FakeAdapter)
    assert len(records(args.output)) == 1
    assert records(args.output)[0]["status"] == "error"

    class Broken:
        def __init__(self, args):
            raise RuntimeError("load failed")

    args.output = tmp_path / "out2"
    args.limit = None
    meta = infer.run(args, Broken)
    assert "load failed" in meta["initialization_error"]
    assert len(records(args.output)) == 2
    assert all(r["status"] == "error" for r in records(args.output))


def test_batch_exception_is_explicit_for_every_sample(tmp_path):
    root, row = make_dataset(tmp_path)
    manifest(root, [row, {**row, "sample_id": "opaque-2"}])

    class Broken(FakeAdapter):
        def predict(self, images):
            raise RuntimeError("GPU out of memory")

    args = args_for(tmp_path, root)
    infer.run(args, Broken)
    assert all("GPU out of memory" in r["error"] for r in records(args.output))


def test_batch_failure_retries_individual_samples_and_keeps_event(tmp_path):
    root, row = make_dataset(tmp_path)
    manifest(root, [row, {**row, "sample_id": "opaque-2"}])

    class BatchFailure(FakeAdapter):
        def predict(self, images):
            if len(images) > 1:
                raise RuntimeError("batch failed")
            return super().predict(images)

    args = args_for(tmp_path, root)
    result = infer.run(args, BatchFailure)
    assert [r["status"] for r in records(args.output)] == ["ok", "ok"]
    assert result["batch_failures"][0]["sample_ids"] == ["opaque-1", "opaque-2"]
    assert "batch failed" in result["batch_failures"][0]["error"]
    assert result["final_execution"]["device"] == "cpu"


def test_adapter_uses_shipped_greedy_or_one_beam_list(monkeypatch):
    calls = []
    reading = types.SimpleNamespace(ids="⿱宀子", confidence=0.9, variant="em", valid=True)

    class Reader:
        def __init__(self, checkpoint, device):
            calls.append((checkpoint, device))
            self.device = device

        def read(self, image, tta):
            calls.append(("greedy", image, tta))
            return reading

        def read_topk(self, image, k, tta):
            calls.append(("beam", image, k, tta))
            return [reading, reading]

    fake = types.ModuleType("han2ids.infer")
    fake.Han2IDS = Reader
    fake.tensor = lambda x: x
    fake.variants = lambda x: [("em", x)]
    grammar = types.ModuleType("han2ids.grammar")
    grammar.generate = lambda *args: None
    grammar.valid_ids = lambda x: True
    monkeypatch.setitem(sys.modules, "han2ids.infer", fake)
    monkeypatch.setitem(sys.modules, "han2ids.grammar", grammar)
    args = types.SimpleNamespace(checkpoint=Path("v01.pt"), device="cpu", threads=1,
                                 decode="beam5", no_tta=True)
    adapter = infer.HanAdapter(args)
    candidates = adapter.predict(["image"])[0]
    assert len(candidates) == 2 and calls[-1] == ("beam", "image", 5, False)
    assert not any(call[0] == "greedy" for call in calls)
    args.decode = "greedy"
    adapter = infer.HanAdapter(args)
    assert len(adapter.predict(["image"])[0]) == 1
    assert calls[-1] == ("greedy", "image", False)


def test_greedy_batched_uses_em_preprocessing_and_checkpoint_model(monkeypatch):
    import torch
    calls = []
    model = object()

    class Reader:
        def __init__(self, checkpoint, device):
            calls.append(("checkpoint", checkpoint, device))
            self.model = model
            self.device = device
            self.itos = ["checkpoint_vocab"]
            self.vocab = types.SimpleNamespace(decode=lambda tokens: {1: "⿱宀子", 2: "⿰木木"}[tokens[0]])

    fake = types.ModuleType("han2ids.infer")
    fake.Han2IDS = Reader
    fake.variants = lambda image: [("em", image + 10), ("crop", 999)]
    fake.tensor = lambda em: torch.tensor([em], dtype=torch.float32)
    grammar = types.ModuleType("han2ids.grammar")

    def generate(actual_model, batch, itos):
        assert actual_model is model and itos == ["checkpoint_vocab"]
        assert batch.tolist() == [[11.0], [12.0]]
        calls.append("generate")
        return torch.tensor([[1], [2]]), torch.tensor([0.9, 0.8])

    grammar.generate = generate
    grammar.valid_ids = lambda text: text == "⿱宀子"
    monkeypatch.setitem(sys.modules, "han2ids.infer", fake)
    monkeypatch.setitem(sys.modules, "han2ids.grammar", grammar)
    args = types.SimpleNamespace(checkpoint=Path("v02.pt"), device="cpu", threads=1,
                                 decode="greedy-batched", no_tta=True)
    results = infer.HanAdapter(args).predict([1, 2])
    assert [row[0]["text"] for row in results] == ["⿱宀子", "⿰木木"]
    assert [row[0]["valid"] for row in results] == [True, False]
    assert [row[0]["variant"] for row in results] == ["em", "em"]
    assert calls == [("checkpoint", Path("v02.pt"), "cpu"), "generate"]


@pytest.mark.parametrize("system", ["han2ids", "glyphstudio"])
def test_cuda_fraction_applied_before_adapter_and_logged(tmp_path, monkeypatch, system):
    root, row = make_dataset(tmp_path)
    manifest(root, [row])
    app = tmp_path / "app"
    if system == "glyphstudio":
        (app / "models" / "ids").mkdir(parents=True)
        (app / "models" / "ids" / "inference_config.json").write_text("{}")
    args = args_for(tmp_path, root, system=system, app=app if system == "glyphstudio" else None,
                    device="cuda", cuda_memory_fraction=0.1)
    monkeypatch.setattr(infer, "adapter_files", lambda args: [])
    calls = []
    fake_cuda = types.SimpleNamespace(is_available=lambda: True, device_count=lambda: 2,
                                     set_per_process_memory_fraction=lambda value, gpu: calls.append((value, gpu)))
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=fake_cuda))

    def factory(args):
        assert calls == [(0.1, 0)]
        return FakeAdapter(args)

    metadata = infer.run(args, factory)
    assert metadata["settings"]["cuda_memory_fraction"] == 0.1
    assert metadata["settings"]["cuda_memory_cap_scope"] == "PyTorch CUDA allocator only"


def test_cuda_fraction_failure_is_reported(tmp_path, monkeypatch):
    root, row = make_dataset(tmp_path)
    manifest(root, [row])
    args = args_for(tmp_path, root, device="cuda", cuda_memory_fraction=0.1)
    fake = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))
    monkeypatch.setitem(sys.modules, "torch", fake)
    metadata = infer.run(args, FakeAdapter)
    assert "unavailable" in metadata["initialization_error"]
    assert records(args.output)[0]["status"] == "error"
    for value in ("nan", "0", "-0.1", "1.01"):
        with pytest.raises(Exception):
            infer.cuda_fraction(value)


def test_glyph_adapter_preserves_runner_outputs_and_warnings(monkeypatch, tmp_path):
    calls = []

    class Reader:
        def __init__(self, path, **kwargs):
            calls.append((path, kwargs))
            self.device = "cuda:1"
            self.warnings = []

        def predict(self, images):
            self.device = "cpu"
            self.warnings.append("GPU fallback")
            return [[{"text": "字", "raw_ids": ["字"], "score": 0.7}]]

    fake = types.ModuleType("glyphstudio.inference")
    fake.IDSModelRunner = Reader
    package = types.ModuleType("glyphstudio")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, "glyphstudio", package)
    monkeypatch.setitem(sys.modules, "glyphstudio.inference", fake)
    args = types.SimpleNamespace(app=tmp_path, device="cuda", threads=3, gpu_index=1)
    adapter = infer.GlyphAdapter(args)
    assert calls == [(tmp_path / "models" / "ids", {"threads": 3, "preference": "cuda", "gpu_index": 1})]
    assert adapter.predict(["image"])[0][0]["raw_ids"] == ["字"]
    assert adapter.execution() == {"device": "cpu", "warnings": ["GPU fallback"]}


def test_parser_and_output_directory_safety(tmp_path):
    root, row = make_dataset(tmp_path)
    manifest(root, [row])
    with pytest.raises(SystemExit):
        infer.main(["--dataset", str(root), "--system", "han2ids", "--output", str(tmp_path / "o")])
    with pytest.raises(SystemExit):
        infer.parser().parse_args(["--dataset", str(root), "--system", "han2ids", "--output", "x", "--batch-size", "0"])
    with pytest.raises(SystemExit):
        infer.main(["--dataset", str(root), "--system", "han2ids", "--checkpoint", "model.pt",
                    "--output", "x", "--decode", "greedy-batched"])
    args = args_for(tmp_path, root, output=root / "results")
    with pytest.raises(ValueError, match="outside"):
        infer.run(args, FakeAdapter)
