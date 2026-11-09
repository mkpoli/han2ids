"""Command line entry point."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .infer import Han2IDS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="han2ids", description="Read an IDS from a Mincho glyph image.")
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--checkpoint", type=Path,
                        default=Path(os.environ.get("HAN2IDS_MODEL", "models/han2ids-v0.1.pt")))
    parser.add_argument("--json", action="store_true", help="one JSON object per image")
    parser.add_argument("--no-tta", action="store_true", help="use only the em-box reading")
    args = parser.parse_args(argv)

    reader = Han2IDS(args.checkpoint)
    for image in args.images:
        reading = reader.read_path(image, tta=not args.no_tta)
        if args.json:
            print(json.dumps({
                "image": str(image), "ids": reading.ids, "confidence": round(reading.confidence, 4),
                "variant": reading.variant, "valid": reading.valid,
            }, ensure_ascii=False))
        else:
            print(f"{image}\t{reading.ids}\t{reading.confidence:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
