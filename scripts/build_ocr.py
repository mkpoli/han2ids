#!/usr/bin/env python3
"""Assemble the static site for the /ocr Worker."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "demo" / "static"
TARGET = ROOT / "build" / "ocr"
REQUIRED = (
    "models/encoder-int8.onnx",
    "models/decoder-int8.onnx",
    "models/itos.json",
    "ort/ort.wasm.min.mjs",
    "ort/ort-wasm-simd-threaded.mjs",
    "ort/ort-wasm-simd-threaded.wasm",
)


def main() -> int:
    missing = [name for name in REQUIRED if not (SOURCE / name).exists()]
    if missing:
        print("Missing demo assets: " + ", ".join(missing))
        print("Run scripts/export_onnx.py and demo/prepare.py first.")
        return 1
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(SOURCE, TARGET)
    total = sum(path.stat().st_size for path in TARGET.rglob("*") if path.is_file())
    print(f"{TARGET}\t{total / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
