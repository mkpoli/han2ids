#!/usr/bin/env python3
"""Time inference on a preselected input-only manifest.

Run with ``python -m benchmark.timing``. Images are verified and decoded before
measurement; each measurement includes adapter preprocessing and prediction.
The same manifest order and adapter configuration are used for both scenarios.
Each warmup and measurement is a full pass through the selected inputs. The
last batch can be smaller than the requested batch size. Each measured pass is
saved as a benchmark.score run directory. With --limit, scoring requires a
dataset containing the emitted selected-inputs.jsonl as inputs.jsonl and
matching references.jsonl.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path

from benchmark import infer


def quantile(values, probability):
    """Linear-interpolated empirical quantile (type 7)."""
    if not values or not 0 <= probability <= 1:
        raise ValueError("quantile needs observations and a probability in [0, 1]")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def device_kind(device):
    value = str(device).lower()
    if value == "cpu":
        return "cpu"
    if value == "cuda" or value.startswith("cuda:"):
        return "cuda"
    if value == "mps" or value.startswith("mps:"):
        return "mps"
    raise RuntimeError(f"unsupported or unknown actual device: {device}")


def synchronize(device):
    kind = device_kind(device)
    if kind == "cuda":
        import torch
        torch.cuda.synchronize(device)
    elif kind == "mps":
        import torch
        torch.mps.synchronize()


def timed_call(call, device, clock=time.perf_counter_ns, sync=synchronize):
    """Measure a completed call; synchronization is outside the timed interval."""
    sync(device)
    start = clock()
    try:
        result = call()
    finally:
        sync(device)
    elapsed = clock() - start
    if elapsed <= 0:
        raise RuntimeError("timer produced a nonpositive duration")
    return result, elapsed


def checked_execution(adapter, requested, initial=None):
    execution = adapter.execution()
    if not isinstance(execution, dict) or not isinstance(execution.get("device"), str):
        raise RuntimeError("adapter did not report its actual device")
    kind = device_kind(execution["device"])
    warnings = execution.get("warnings")
    if not isinstance(warnings, list) or any(not isinstance(w, str) for w in warnings):
        raise RuntimeError("adapter did not report execution warnings")
    if requested != "auto" and kind != requested:
        raise RuntimeError(f"device fallback: requested {requested}, actual {execution['device']}")
    if any("fallback" in w.lower() or "fall back" in w.lower() or "falling back" in w.lower() for w in warnings):
        raise RuntimeError(f"adapter reported fallback: {warnings}")
    if initial is not None and execution != initial:
        raise RuntimeError(f"adapter execution changed: {initial} -> {execution}")
    return execution


def prediction_records(rows, results, execution):
    if not isinstance(results, (list, tuple)) or len(results) != len(rows):
        raise RuntimeError("adapter returned wrong batch length")
    records = []
    for row, candidates in zip(rows, results):
        if not isinstance(candidates, list) or not candidates:
            raise RuntimeError(f"adapter returned no candidates for {row['sample_id']}")
        ranked = []
        for rank, candidate in enumerate(candidates, 1):
            if not isinstance(candidate, dict) or not isinstance(candidate.get("text"), str):
                raise RuntimeError(f"invalid candidate for {row['sample_id']}")
            ranked.append({**candidate, "rank": rank})
        records.append({"sample_id": row["sample_id"], "status": "ok", "candidates": ranked,
                        "error": None, "execution": execution})
    # Reject non-finite or non-serializable output before reporting success.
    json.dumps(records, ensure_ascii=False, allow_nan=False)
    return records


def measure_pass(adapter, rows, images, batch_size, requested, execution,
                 clock=time.perf_counter_ns, sync=synchronize):
    durations, records, sizes = [], [], []
    for start in range(0, len(rows), batch_size):
        batch_rows, batch_images = rows[start:start + batch_size], images[start:start + batch_size]
        checked_execution(adapter, requested, execution)
        result, elapsed = timed_call(lambda: adapter.predict(batch_images), execution["device"], clock, sync)
        current = checked_execution(adapter, requested, execution)
        records.extend(prediction_records(batch_rows, result, current))
        durations.append(elapsed)
        sizes.append(len(batch_rows))
    return durations, sizes, records


def torch_settings(adapter):
    """Record observable precision settings; do not infer hidden adapter policy."""
    settings = {"precision_policy": "adapter-managed; see model configuration", "model_parameter_dtypes": None}
    model = getattr(getattr(adapter, "reader", None), "model", None)
    if model is not None and callable(getattr(model, "parameters", None)):
        settings["model_parameter_dtypes"] = sorted({str(p.dtype) for p in model.parameters()})
    try:
        import torch
        settings.update({"torch_num_threads": torch.get_num_threads(),
                         "torch_num_interop_threads": torch.get_num_interop_threads(),
                         "float32_matmul_precision": torch.get_float32_matmul_precision(),
                         "default_dtype": str(torch.get_default_dtype()),
                         "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
                         "cuda_runtime_version": torch.version.cuda,
                         "cudnn_version": torch.backends.cudnn.version(),
                         "cudnn_benchmark": torch.backends.cudnn.benchmark,
                         "cuda_matmul_allow_tf32": torch.backends.cuda.matmul.allow_tf32,
                         "cudnn_allow_tf32": torch.backends.cudnn.allow_tf32,
                         "thread_environment": {key: os.environ.get(key) for key in
                                                ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")}})
        device = adapter.execution()["device"]
        if device_kind(device) == "cuda":
            settings["cuda_device_name"] = torch.cuda.get_device_name(device)
            settings["cuda_device_capability"] = list(torch.cuda.get_device_capability(device))
    except ImportError:
        settings["torch_available"] = False
    return settings


def run(args, adapter_factory=None, clock=time.perf_counter_ns, sync=synchronize):
    if args.batch_size <= 1 or args.warmup < 3 or args.repeats < 2:
        raise ValueError("batch size must exceed 1, warmup must be at least 3, repeats at least 2")
    if args.threads < 1 or args.gpu_index < 0 or (args.limit is not None and args.limit < 1):
        raise ValueError("invalid threads, GPU index, or limit")
    dataset, output = args.dataset.resolve(), args.output.resolve()
    if output == dataset or output.is_relative_to(dataset):
        raise ValueError("output must be outside the dataset directory")
    output.mkdir(parents=True, exist_ok=False)
    report = {"format": "ids-inference-timing-v1", "status": "error", "error": None,
              "device_requested": args.device, "actual_execution": None,
              "fallback": None, "scenarios": {},
              "caveat": "Other processes and shared accelerator usage may affect timings; isolation is not measured.",
              "timing_scope": "Predecoded verified images; adapter preprocessing and prediction; synchronization before and after each call. Serialization and validation excluded.",
              "synchronization": "torch.cuda.synchronize for CUDA; torch.mps.synchronize for MPS; CPU synchronous",
              "quantile": "linear interpolation, type 7, over batch durations",
              "total_elapsed_scope": "sum of measured batch durations; excludes validation, serialization and loop overhead"}
    images = []
    adapter = None
    try:
        manifest_path = dataset / "inputs.jsonl"
        source_manifest = manifest_path.read_bytes()
        rows = infer.load_manifest(dataset)
        if manifest_path.read_bytes() != source_manifest:
            raise RuntimeError("input manifest changed while loading")
        if args.limit is not None:
            rows = rows[:args.limit]
        if not rows:
            raise ValueError("selected manifest is empty")
        selected_manifest = b"".join(source_manifest.splitlines(keepends=True)[:len(rows)])
        report.update({"source_manifest_sha256": hashlib.sha256(source_manifest).hexdigest(),
                       "manifest_sha256": hashlib.sha256(selected_manifest).hexdigest(),
                       "selected_manifest": "selected-inputs.jsonl",
                       "scoring_note": "With --limit, create a scoring dataset with selected-inputs.jsonl as inputs.jsonl and references restricted to the same sample IDs.",
                       "input_ids": [row["sample_id"] for row in rows],
                       "inputs": rows, "system": args.system,
                       "files_sha256": infer.hash_files(infer.adapter_files(args)),
                       "runner_sha256": infer.file_hash(Path(__file__)),
                       "infer_sha256": infer.file_hash(Path(infer.__file__)),
                       "software": infer.versions(),
                       "settings": {"device_requested": args.device, "gpu_index": args.gpu_index,
                                    "cuda_memory_fraction": args.cuda_memory_fraction,
                                    "threads": args.threads, "batch_size": args.batch_size,
                                    "warmup_passes": args.warmup, "measurement_passes": args.repeats,
                                    "limit": args.limit,
                                    "decode": args.decode if args.system == "han2ids" else "shipped-ensemble-beam",
                                    "tta": not args.no_tta if args.system == "han2ids" else None,
                                    "concurrency": "single process, serial batches"}})
        if args.system == "glyphstudio":
            report["model_config"] = json.loads((args.app / "models" / "ids" / "inference_config.json").read_text(encoding="utf-8"))
        for row in rows:
            images.append(infer.open_image(dataset, row))
        if args.cuda_memory_fraction is not None:
            if not 0 < args.cuda_memory_fraction <= 1 or args.device not in ("auto", "cuda"):
                raise ValueError("CUDA memory fraction requires auto or cuda and a fraction in (0, 1]")
            import torch
            if not torch.cuda.is_available() or args.gpu_index >= torch.cuda.device_count():
                raise RuntimeError("CUDA memory limit requested but CUDA device is unavailable")
            torch.cuda.set_per_process_memory_fraction(args.cuda_memory_fraction, args.gpu_index)
        # Auto may resolve to CUDA. Synchronize the candidate CUDA device before
        # construction; this initializes its runtime and is excluded from load time.
        load_device = args.device
        if load_device == "auto":
            try:
                import torch
                load_device = f"cuda:{args.gpu_index}" if torch.cuda.is_available() else "cpu"
            except ImportError:
                load_device = "cpu"
        elif load_device == "cuda":
            load_device = f"cuda:{args.gpu_index}"
        sync(load_device)
        start = clock()
        try:
            adapter = (adapter_factory or (infer.HanAdapter if args.system == "han2ids" else infer.GlyphAdapter))(args)
            initial = adapter.execution()
            report["actual_execution"] = initial
        finally:
            sync(load_device)
        if device_kind(initial["device"]) != device_kind(load_device):
            sync(initial["device"])
        load_ns = clock() - start
        if load_ns <= 0:
            raise RuntimeError("timer produced a nonpositive load duration")
        report["cold_load_ns"] = load_ns
        report["cold_load_scope"] = "adapter construction; accelerator runtime synchronization/context setup before start excluded"
        execution = checked_execution(adapter, args.device, initial)
        if args.device == "auto" and device_kind(execution["device"]) != device_kind(load_device):
            raise RuntimeError(f"device fallback or unexpected auto selection: expected {load_device}, actual {execution['device']}; use an explicit device")
        if device_kind(execution["device"]) == "cuda":
            actual_index = execution["device"].split(":", 1)[1] if ":" in execution["device"] else "0"
            if actual_index != str(args.gpu_index):
                raise RuntimeError(f"GPU index mismatch: requested {args.gpu_index}, actual {execution['device']}")
        report["fallback"] = False
        report["precision_and_threads"] = torch_settings(adapter)
        pending = {}
        for name, batch_size in (("interactive", 1), ("throughput", args.batch_size)):
            for _ in range(args.warmup):
                measure_pass(adapter, rows, images, batch_size, args.device, execution, clock, sync)
            all_durations, all_sizes, passes = [], [], []
            for repeat in range(args.repeats):
                durations, sizes, records = measure_pass(adapter, rows, images, batch_size, args.device, execution, clock, sync)
                all_durations.extend(durations)
                all_sizes.extend(sizes)
                content = "".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in records)
                run_name = f"{name}-pass-{repeat + 1}"
                prediction_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                run_metadata = {"format": "ids-inference-run-v1", "system": args.system,
                                "manifest_sha256": report["manifest_sha256"],
                                "source_manifest_sha256": report["source_manifest_sha256"],
                                "output_predictions_sha256": prediction_hash,
                                "files_sha256": report["files_sha256"],
                                "runner_sha256": report["runner_sha256"],
                                "infer_sha256": report["infer_sha256"],
                                "software": report["software"],
                                "settings": {**report["settings"], "batch_size": batch_size},
                                "initial_execution": execution, "final_execution": execution,
                                "precision_and_threads": report["precision_and_threads"],
                                "samples": len(records), "initialization_error": None,
                                "batch_failures": [], "timing_scenario": name,
                                "timing_pass": repeat + 1}
                if "model_config" in report:
                    run_metadata["model_config"] = report["model_config"]
                pending[run_name] = (content, run_metadata)
                passes.append({"run": run_name, "predictions": f"{run_name}/predictions.jsonl",
                               "predictions_sha256": prediction_hash,
                               "elapsed_ns": sum(durations), "inputs": len(records)})
            total = sum(all_durations)
            report["scenarios"][name] = {"batch_size": batch_size, "batch_sizes": all_sizes,
                                         "batch_elapsed_ns": all_durations, "total_elapsed_ns": total,
                                         "p50_batch_ns": quantile(all_durations, .5),
                                         "p95_batch_ns": quantile(all_durations, .95),
                                         "inputs": len(rows) * args.repeats,
                                         "inputs_per_second": len(rows) * args.repeats * 1e9 / total,
                                         "passes": passes}
        (output / "selected-inputs.jsonl").write_bytes(selected_manifest)
        for run_name, (content, run_metadata) in pending.items():
            run_dir = output / run_name
            run_dir.mkdir()
            (run_dir / "predictions.jsonl").write_text(content, encoding="utf-8")
            (run_dir / "run.json").write_text(json.dumps(run_metadata, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
        report["status"] = "ok"
    except Exception as exc:
        report["error"] = infer.error_text(exc)
        report["scenarios"] = {}
        if adapter is not None:
            try:
                report["final_execution"] = adapter.execution()
            except Exception as execution_error:
                report["execution_error"] = infer.error_text(execution_error)
        if ("fallback" in str(exc).lower() or "execution changed" in str(exc).lower()
                or "index mismatch" in str(exc).lower()
                or (report.get("final_execution") is not None and report.get("actual_execution") != report["final_execution"])):
            report["fallback"] = True
        raise
    finally:
        for image in images:
            image.close()
        (output / "timing.json").write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = infer.parser()
    parser.description = __doc__
    parser.add_argument("--warmup", type=infer.positive, default=3, help="full warmup passes per scenario (minimum 3)")
    parser.add_argument("--repeats", type=infer.positive, default=3, help="full measured passes per scenario (minimum 2)")
    args = parser.parse_args(argv)
    if args.system == "han2ids":
        if args.checkpoint is None or args.app is not None or args.gpu_index != 0:
            parser.error("han2ids requires --checkpoint, disallows --app, and accepts only GPU index 0")
        if args.decode == "greedy-batched" and not args.no_tta:
            parser.error("--decode greedy-batched requires --no-tta")
    elif args.app is None or args.checkpoint is not None or args.decode != "greedy" or args.no_tta:
        parser.error("glyphstudio requires --app; --checkpoint, --decode and --no-tta are han2ids-only")
    try:
        run(args)
    except Exception as exc:
        parser.exit(2, f"error: {infer.error_text(exc)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
