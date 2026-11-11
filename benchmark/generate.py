"""Generate a paired, unreviewed glyph benchmark from a JSONL manifest."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import platform
import tempfile
from pathlib import Path

import fontTools
import numpy as np
from PIL import __version__ as pillow_version, features

from .legacy import publish
from .render import Face, RenderError, audit_legacy_crop, render, select_face, sha256_file

RENDERER = "ink-fit-v1"


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse_font(spec: str) -> tuple[str, int, Path]:
    try:
        family, index, path = spec.split("=", 2)
        if not family or not path:
            raise ValueError
        number = int(index)
        if number < 0:
            raise ValueError
        return family, number, Path(path)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("font must be FAMILY=FACE_INDEX=PATH") from exc


def generate(manifest: Path, output: Path, mappings: list[tuple[str, int, Path]], *,
             size: int = 224, padding: int = 12, limit: int | None = None,
             original_array: Path | None = None, audit_legacy: bool = False) -> None:
    if not mappings:
        raise ValueError("at least one explicit font mapping is required")
    if size <= 0 or padding < 1 or 2 * padding >= size:
        raise ValueError("size must exceed twice the positive padding")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    manifest = manifest.resolve(strict=True)
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output already exists: {output}")
    rows = []
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"blank manifest line {line_number}")
        row = json.loads(line)
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k] for k in ("char", "ids", "font")):
            raise ValueError(f"manifest line {line_number} must have nonempty string char, ids and font")
        rows.append(row)
    if not rows:
        raise ValueError("manifest is empty")
    manifest_hash = sha256_file(manifest)
    generator_path = Path(__file__).resolve()
    renderer_path = generator_path.with_name("render.py")
    generator_hash = sha256_file(generator_path)
    renderer_hash = sha256_file(renderer_path)
    original = None
    original_metadata = None
    if original_array is not None:
        original_array = original_array.resolve(strict=True)
        original = np.load(original_array, mmap_mode="r", allow_pickle=False)
        if original.ndim != 3 or original.dtype != np.uint8 or len(original) != len(rows):
            raise ValueError("original array must be uint8, N×H×W and match the full manifest length")
        original_metadata = {"path": str(original_array), "shape": list(original.shape),
                             "dtype": str(original.dtype), "row_hash": "sha256 of C-order uint8 pixels"}
    faces: dict[str, list[Face]] = {}
    all_faces = []
    for family, index, path in mappings:
        face = Face.load(family, path, index)
        faces.setdefault(family, []).append(face)
        all_faces.append(face.metadata())
    selected = rows[:limit]
    output.parent.mkdir(parents=True, exist_ok=True)
    # Work in a sibling directory and publish only after every sample succeeds.
    with tempfile.TemporaryDirectory(prefix=".benchmark-", dir=output.parent) as temp:
        base = Path(temp)
        (base / "images").mkdir()
        seen = set()
        audit_context = ((base / "legacy-audit.jsonl").open("w", encoding="utf-8", newline="\n")
                         if audit_legacy else nullcontext(None))
        with (base / "inputs.jsonl").open("w", encoding="utf-8", newline="\n") as inputs, \
             (base / "references.jsonl").open("w", encoding="utf-8", newline="\n") as references, \
             audit_context as audit:
            for row_index, row in enumerate(selected):
                try:
                    face = select_face(row["char"], faces.get(row["font"], []))
                    image = render(face, row["char"], size, padding)
                    legacy = audit_legacy_crop(face, row["char"]) if audit is not None else None
                except (ValueError, RenderError) as exc:
                    raise RenderError(f"source row {row_index} ({row['font']}): {exc}") from exc
                identity = {"manifest_sha256": manifest_hash, "source_row": row_index,
                            "font_sha256": face.sha256, "face_index": face.index,
                            "renderer": RENDERER, "size": size, "padding": padding}
                sample_id = hashlib.sha256(json_bytes(identity)).hexdigest()
                if sample_id in seen:
                    raise RuntimeError("duplicate sample ID")
                seen.add(sample_id)
                relative = f"images/{sample_id}.png"
                image_path = base / relative
                image.save(image_path, format="PNG", optimize=False, compress_level=9)
                image_hash = sha256_file(image_path)
                inp = {"sample_id": sample_id, "image": relative, "image_sha256": image_hash}
                ref = {"sample_id": sample_id, "char": row["char"], "ids": row["ids"],
                       "font": row["font"], "font_sha256": face.sha256, "face_index": face.index,
                       "source_row": row_index, "source": row, "review_status": "unreviewed"}
                if original is not None:
                    ref["original_pixels_sha256"] = hashlib.sha256(original[row_index].tobytes(order="C")).hexdigest()
                inputs.write(json_bytes(inp).decode("utf-8") + "\n")
                references.write(json_bytes(ref).decode("utf-8") + "\n")
                if audit is not None:
                    audit.write(json_bytes({"sample_id": sample_id, **legacy}).decode("utf-8") + "\n")
        if sha256_file(generator_path) != generator_hash or sha256_file(renderer_path) != renderer_hash:
            raise RuntimeError("generator or renderer changed during generation")
        metadata = {"schema_version": 1, "renderer": RENDERER, "size": size, "padding": padding,
                    "generator_sha256": generator_hash, "renderer_sha256": renderer_hash,
                    "layout_engine": "Pillow BASIC",
                    "legacy_audit_layout_engine": "Pillow default" if audit_legacy else None,
                    "render_em": 256, "source_manifest": {"path": str(manifest), "sha256": manifest_hash,
                                                           "rows": len(rows)},
                    "original_array": original_metadata, "output_rows": len(selected), "legacy_crop_audit": audit_legacy,
                    "fonts": all_faces, "software": {"python": platform.python_version(),
                    "pillow": pillow_version, "freetype": features.version_module("freetype2"),
                    "fonttools": fontTools.__version__, "numpy": np.__version__},
                    "reference_status": "unreviewed"}
        (base / "fonts.json").write_bytes(json_bytes(metadata) + b"\n")
        publish(base, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="new output directory")
    parser.add_argument("--font", required=True, action="append", type=parse_font,
                        help="FAMILY=FACE_INDEX=PATH; repeat in coverage priority order")
    parser.add_argument("--original-array", type=Path, help="paired original NPY (memory mapped)")
    parser.add_argument("--audit-legacy-crop", action="store_true", help="measure lost ink in the v0.3 crop")
    parser.add_argument("--size", type=int, default=224)
    parser.add_argument("--padding", type=int, default=12)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    generate(args.manifest, args.out, args.font, size=args.size, padding=args.padding,
             limit=args.limit, original_array=args.original_array, audit_legacy=args.audit_legacy_crop)


if __name__ == "__main__":
    main()
