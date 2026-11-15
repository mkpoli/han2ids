"""Command line entry point."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from PIL import Image

from .infer import Han2IDS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="han2ids", description="Read an IDS from a Mincho glyph image.")
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--checkpoint", type=Path,
                        default=Path(os.environ.get("HAN2IDS_MODEL", "models/han2ids-v0.5.pt")))
    parser.add_argument("--json", action="store_true", help="one JSON object per image")
    parser.add_argument("--no-tta", action="store_true", help="use only the em-box reading")
    parser.add_argument("--top-k", type=int, default=1, help="beam alternatives, at most this many")
    parser.add_argument("--variants", action="store_true",
                        help="also name the registered form the image draws; see docs/variant-match.md")
    parser.add_argument("--char", help="with --variants, match the forms of this character instead of the reading's")
    args = parser.parse_args(argv)
    if args.char and not args.variants:
        parser.error("--char needs --variants")
    if args.variants and args.top_k > 1:
        parser.error("--variants names the form of one reading; drop --top-k")

    reader = Han2IDS(args.checkpoint)
    matcher = None
    if args.variants:
        from .variants import VariantMatcher
        matcher = VariantMatcher(reader)
    for image in args.images:
        if args.top_k > 1:
            with Image.open(image) as opened:
                readings = reader.read_topk(opened, k=args.top_k, tta=not args.no_tta)
            if args.json:
                print(json.dumps({"image": str(image), "readings": [
                    {"ids": item.ids, "unified": item.unified, "confidence": round(item.confidence, 4), "variant": item.variant, "valid": item.valid}
                    for item in readings]}, ensure_ascii=False))
            else:
                for index, item in enumerate(readings):
                    print(f"{image}\t{index + 1}\t{item.ids}\t{item.unified}\t{item.confidence:.3f}")
            continue
        with Image.open(image) as opened:
            reading = reader.read(opened, tta=not args.no_tta)
            match = None
            if matcher:
                match = matcher.match(opened, args.char) if args.char else matcher.match_reading(opened, reading.ids)
        if args.json:
            record = {
                "image": str(image), "ids": reading.ids, "unified": reading.unified, "confidence": round(reading.confidence, 4),
                "variant": reading.variant, "valid": reading.valid,
            }
            if match:
                record["variants"] = match.record()
            print(json.dumps(record, ensure_ascii=False))
        else:
            print(f"{image}\t{reading.ids}\t{reading.unified}\t{reading.confidence:.3f}" + (f"\t{match.line()}" if match else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
