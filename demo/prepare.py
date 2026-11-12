#!/usr/bin/env python3
"""Copy the int8 ONNX models and the ONNX Runtime Web files into demo/static."""
from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "demo" / "static"
MODELS = STATIC / "models"
ORT = STATIC / "ort"
ORT_VERSION = "1.31.1"
ORT_FILES = ("ort.wasm.min.mjs", "ort-wasm-simd-threaded.mjs", "ort-wasm-simd-threaded.wasm")


def copy_models(source: Path) -> None:
    MODELS.mkdir(parents=True, exist_ok=True)
    for name in ("encoder-int8.onnx", "decoder-int8.onnx", "itos.json", "forms.json"):
        path = source / name
        if not path.exists():
            raise FileNotFoundError(path)
        shutil.copyfile(path, MODELS / name)
        print(f"{MODELS / name}\t{(MODELS / name).stat().st_size / 1e6:.1f} MB")


def copy_ort(source: Path | None) -> None:
    ORT.mkdir(parents=True, exist_ok=True)
    for name in ORT_FILES:
        local = source / name if source else None
        target = ORT / name
        if local and local.exists():
            shutil.copyfile(local, target)
        else:
            url = f"https://unpkg.com/onnxruntime-web@{ORT_VERSION}/dist/{name}"
            with urllib.request.urlopen(url) as response, target.open("wb") as handle:
                shutil.copyfileobj(response, handle)
        print(f"{target}\t{target.stat().st_size / 1e6:.1f} MB")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prepare-demo", description=__doc__)
    parser.add_argument("--models", type=Path, default=ROOT / "build" / "onnx")
    parser.add_argument("--ort", type=Path, default=None, help="a local onnxruntime-web/dist directory")
    args = parser.parse_args(argv)

    if not (args.models / "encoder-int8.onnx").exists():
        print(f"{args.models} has no int8 model; run scripts/export_onnx.py first.", file=sys.stderr)
        return 1

    copy_models(args.models)
    copy_ort(args.ort)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
