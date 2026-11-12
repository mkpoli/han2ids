"""Export the reader to ONNX and an int8 copy for a browser runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from han2ids.forms import UNIFIED
from han2ids.model import GlyphIDS
from han2ids.tokenizer import BOS


class Encoder(nn.Module):
    def __init__(self, model: GlyphIDS):
        super().__init__()
        self.model = model

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        memory = self.model.encoder.forward_features(images)
        if memory.dim() == 4:
            memory = memory.flatten(2).transpose(1, 2)
        return self.model.memory_proj(memory)


class Decoder(nn.Module):
    def __init__(self, model: GlyphIDS):
        super().__init__()
        self.model = model

    def forward(self, memory: torch.Tensor, tokens: torch.Tensor) -> torch.Tensor:
        model = self.model
        length = tokens.size(1)
        target = model.tok(tokens) * math.sqrt(model.d_model)
        target = target + model.pos(torch.arange(length, device=tokens.device))[None]
        causal = torch.triu(torch.full((length, length), float("-inf"), device=tokens.device), 1)
        out = model.decoder(target, memory, tgt_mask=causal, tgt_key_padding_mask=tokens.eq(0))
        return model.head(out)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="export-onnx", description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "models" / "han2ids-v0.4.pt")
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "onnx")
    parser.add_argument("--max-len", type=int, default=0, help="decoder length; the checkpoint value by default")
    args = parser.parse_args(argv)

    if not args.checkpoint.exists():
        parser.error(f"Checkpoint not found: {args.checkpoint}")

    payload = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    model = GlyphIDS(len(payload["itos"]), payload["args"]["encoder"],
                     max_len=payload["args"].get("max_len", 48))
    model.load_state_dict(payload["model"])
    model.eval()
    max_len = args.max_len or payload["args"].get("max_len", 48)

    args.out.mkdir(parents=True, exist_ok=True)
    encoder = Encoder(model).eval()
    decoder = Decoder(model).eval()
    images = torch.zeros(1, 3, 224, 224)
    with torch.no_grad():
        memory = encoder(images)
    tokens = torch.zeros(1, max_len, dtype=torch.long)
    tokens[0, 0] = BOS

    torch.onnx.export(
        encoder, (images,), str(args.out / "encoder.onnx"),
        input_names=["images"], output_names=["memory"], opset_version=17,
        dynamo=False, do_constant_folding=True, training=torch.onnx.TrainingMode.EVAL,
    )
    torch.onnx.export(
        decoder, (memory, tokens), str(args.out / "decoder.onnx"),
        input_names=["memory", "tokens"], output_names=["logits"], opset_version=17,
        dynamo=False, do_constant_folding=True, training=torch.onnx.TrainingMode.EVAL,
    )
    (args.out / "itos.json").write_text(json.dumps(payload["itos"], ensure_ascii=False) + "\n")
    (args.out / "forms.json").write_text(json.dumps(UNIFIED, ensure_ascii=False) + "\n")

    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic
    except ImportError:
        print("onnxruntime is missing; run with --extra onnx to write the int8 copy.", file=sys.stderr)
        return 1

    for name in ("encoder", "decoder"):
        quantize_dynamic(
            args.out / f"{name}.onnx", args.out / f"{name}-int8.onnx",
            weight_type=QuantType.QInt8,
        )

    files = {}
    for path in sorted(args.out.glob("*.onnx")):
        files[path.name] = {"bytes": path.stat().st_size, "sha256": digest(path)}
    manifest = {
        "source": str(args.checkpoint),
        "image_size": 224,
        "max_len": max_len,
        "files": files,
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

    for name in ("encoder.onnx", "decoder.onnx", "encoder-int8.onnx", "decoder-int8.onnx"):
        size = files[name]["bytes"]
        print(f"{args.out / name}\t{size / 1e6:.1f} MB")
    total = sum(files[name]["bytes"] for name in ("encoder-int8.onnx", "decoder-int8.onnx"))
    print(f"int8 total\t{total / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
