"""Export a shareable benchmark bundle.

Example: python -m benchmark.export --dataset DATASET --run RUN --run RUN2
    --score scores.json --output BUNDLE

Only the known dataset manifests, metadata and audit, each run's predictions
and metadata, and explicitly named score files are included by default. Add
--include-images to archive exactly the manifest's image files as dataset/images.tar.gz;
extract it inside dataset/ before running inference. Image bytes and embedded image
metadata are not redacted; check them and their licenses before publication.
Source fonts and CHISE raw data are excluded. JSON/JSONL at least 1 MiB is gzip-
compressed with mtime zero; decompress *.gz files before using benchmark tools.
Inputs, references and predictions retain their exact bytes and are rejected if
they contain the current absolute HOME path, including JSON-escaped forms.
Metadata and scores have HOME replaced with $HOME in all strings and keys.
Score reports must include dataset and prediction provenance hashes; each scored
run must be included in the bundle. Image export requires Pillow.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
import tempfile


COMPRESS_THRESHOLD = 1024 * 1024


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(data: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    def bad_constant(value):
        raise ValueError(f"invalid JSON constant: {value}")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=bad_constant)


def _transform(value, home: str, *, reject: bool):
    if isinstance(value, str):
        if reject and home in value:
            raise ValueError("HOME path found in an immutable manifest or prediction")
        return value.replace(home, "$HOME") if not reject else value
    if isinstance(value, list):
        return [_transform(item, home, reject=reject) for item in value]
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            new_key = _transform(key, home, reject=reject)
            if new_key in out:
                raise ValueError("JSON keys collide after HOME redaction")
            out[new_key] = _transform(item, home, reject=reject)
        return out
    return value


def _encode(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def _content(source: Path, home: str, immutable: bool):
    """Yield checked bytes; JSONL is processed one line at a time."""
    if source.suffix == ".jsonl":
        with source.open("rb") as stream:
            for line in stream:
                value = _transform(_json(line.decode("utf-8")), home, reject=immutable)
                yield line if immutable else _encode(value)
    else:
        data = source.read_bytes()
        value = _transform(_json(data.decode("utf-8")), home, reject=immutable)
        yield data if immutable else _encode(value)


def _required_file(path: Path, root: Path | None = None) -> Path:
    if not path.is_file():
        raise ValueError(f"required file missing: {path}")
    if root is not None and (path.is_symlink() or not path.resolve().is_relative_to(root)):
        raise ValueError(f"file must be inside its source directory: {path}")
    return path


def _validate_score(path: Path, input_hash: str, reference_hash: str, run_hashes: dict[str, str]):
    data = path.read_bytes()
    report = _json(data.decode("utf-8"))
    if not isinstance(report, dict) or not isinstance(report.get("runs"), dict):
        raise ValueError(f"score {path.name}: expected a score report with runs")
    provenance = report.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError(f"score {path.name}: provenance missing")
    if provenance.get("inputs_sha256") != input_hash or provenance.get("references_sha256") != reference_hash:
        raise ValueError(f"score {path.name}: dataset hash mismatch")
    hashes = provenance.get("prediction_sha256")
    if not isinstance(hashes, dict) or not hashes or hashes.keys() != report["runs"].keys():
        raise ValueError(f"score {path.name}: scored runs and prediction hashes must match")
    for name, digest in hashes.items():
        if name not in run_hashes or digest != run_hashes[name]:
            raise ValueError(f"score {path.name}: run {name!r} missing or prediction hash mismatch")
    if "runs" in provenance and (not isinstance(provenance["runs"], dict) or provenance["runs"].keys() != hashes.keys()):
        raise ValueError(f"score {path.name}: provenance runs do not match scored runs")
    return hashlib.sha256(data).hexdigest()


def _images(dataset: Path, home: str, input_hash: str):
    images = []
    seen_paths, seen_resolved = set(), set()
    digest = hashlib.sha256()
    with (dataset / "inputs.jsonl").open("rb") as handle:
        for line in handle:
            digest.update(line)
            row = _transform(_json(line.decode("utf-8")), home, reject=True)
            if not isinstance(row, dict):
                raise ValueError("image manifest row must be an object")
            name, sha = row.get("image"), row.get("image_sha256")
            if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
                raise ValueError("invalid image path")
            rel = PurePosixPath(name)
            if (rel.is_absolute() or name != rel.as_posix() or ".." in rel.parts
                    or rel.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}
                    or home in name):
                raise ValueError("image path must be a safe relative raster path")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
                raise ValueError("invalid image SHA-256")
            if name in seen_paths:
                raise ValueError("duplicate image path")
            path = (dataset / name).resolve(strict=True)
            if not path.is_relative_to(dataset) or not path.is_file():
                raise ValueError("image must resolve to a file inside the dataset")
            if path in seen_resolved:
                raise ValueError("duplicate resolved image path")
            seen_paths.add(name)
            seen_resolved.add(path)
            images.append((name, path, sha.lower()))
    if digest.hexdigest() != input_hash:
        raise ValueError("input manifest changed during export")
    if not images:
        raise ValueError("input manifest contains no images")
    return sorted(images)


class _HashReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, size):
        data = self.stream.read(size)
        self.digest.update(data)
        return data


def _raster_header(name: str, header: bytes) -> bool:
    suffix = PurePosixPath(name).suffix.lower()
    if suffix == ".png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix in {".jpg", ".jpeg"}:
        return header.startswith(b"\xff\xd8\xff")
    if suffix == ".gif":
        return header.startswith((b"GIF87a", b"GIF89a"))
    if suffix == ".bmp":
        return header.startswith(b"BM")
    if suffix in {".tif", ".tiff"}:
        return header.startswith((b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"))
    return suffix == ".webp" and header[:4] == b"RIFF" and header[8:12] == b"WEBP"


def _image_archive(base: Path, images, input_hash: str):
    from PIL import Image

    formats = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".bmp": "BMP",
               ".tif": "TIFF", ".tiff": "TIFF", ".webp": "WEBP", ".gif": "GIF"}
    target = base / "dataset" / "images.tar.gz"
    with target.open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as gz:
        with tarfile.open(fileobj=gz, mode="w|", format=tarfile.PAX_FORMAT) as archive:
            for name, path, expected in images:
                with path.open("rb") as image:
                    if not _raster_header(name, image.read(16)):
                        raise ValueError(f"invalid raster image signature: {name}")
                    image.seek(0)
                    try:
                        with Image.open(image) as checked:
                            if checked.format != formats[PurePosixPath(name).suffix.lower()]:
                                raise ValueError(f"raster image format mismatch: {name}")
                            checked.verify()
                        image.seek(0)
                        with Image.open(image) as decoded:
                            decoded.load()
                    except (OSError, SyntaxError) as exc:
                        raise ValueError(f"invalid raster image: {name}") from exc
                    image.seek(0)
                    size = os.fstat(image.fileno()).st_size
                    info = tarfile.TarInfo(name)
                    info.size, info.mode, info.mtime = size, 0o644, 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    reader = _HashReader(image)
                    archive.addfile(info, reader)
                    if reader.digest.hexdigest() != expected or os.fstat(image.fileno()).st_size != size:
                        raise ValueError(f"image SHA-256 mismatch: {name}")
    return {"path": "dataset/images.tar.gz", "compression": "tar+gzip",
            "stored_sha256": _hash(target), "extract_to": "dataset/",
            "input_manifest": "dataset/inputs.jsonl", "input_manifest_sha256": input_hash,
            "images": [{"path": name, "sha256": sha} for name, _, sha in images]}


def export(dataset: Path, runs: list[Path], scores: list[Path], output: Path,
           *, compress_threshold: int = COMPRESS_THRESHOLD, include_images: bool = False) -> dict:
    """Create a new bundle and return its manifest; source files are read-only."""
    if not runs:
        raise ValueError("at least one run is required")
    if compress_threshold < 0:
        raise ValueError("compression threshold must be nonnegative")
    home = str(Path.home())
    if home == "/" or not Path(home).is_absolute():
        raise ValueError("HOME must identify an absolute, non-root directory")
    dataset = Path(dataset).resolve(strict=True)
    run_paths = [Path(path).resolve(strict=True) for path in runs]
    score_paths = [Path(path).resolve(strict=True) for path in scores]
    if Path(output).is_symlink():
        raise FileExistsError(f"output already exists: {output}")
    output = Path(output).resolve()
    if not dataset.is_dir() or any(not path.is_dir() for path in run_paths):
        raise ValueError("dataset and runs must be directories")
    for source in [dataset, *run_paths, *score_paths]:
        if output == source or output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError("source and destination overlap")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    if len({p.name for p in run_paths}) != len(run_paths):
        raise ValueError("duplicate run names")
    if len({p.name for p in score_paths}) != len(score_paths):
        raise ValueError("duplicate score names")
    if any(home in p.name for p in [*run_paths, *score_paths]):
        raise ValueError("HOME path found in a source name")

    files: list[tuple[Path, Path, bool]] = []
    for name in ("inputs.jsonl", "references.jsonl"):
        files.append((_required_file(dataset / name, dataset), Path("dataset") / name, True))
    metadata = [name for name in ("dataset.json", "fonts.json", "subset.json", "review.json") if (dataset / name).exists()]
    if not metadata:
        raise ValueError("dataset metadata missing: expected dataset.json, fonts.json, subset.json or review.json")
    for name in [*metadata, *(["legacy-audit.jsonl"] if (dataset / "legacy-audit.jsonl").exists() else [])]:
        files.append((_required_file(dataset / name, dataset), Path("dataset") / name, False))
    for run in run_paths:
        for name in ("predictions.jsonl", "run.json"):
            files.append((_required_file(run / name, run), Path("runs") / run.name / name,
                          name == "predictions.jsonl"))
    for score in score_paths:
        if score.suffix not in (".json", ".jsonl"):
            raise ValueError("score files must be JSON or JSONL")
        files.append((_required_file(score), Path("scores") / score.name, False))

    # A run's input hash must continue to identify the included input bytes.
    input_hash = _hash(dataset / "inputs.jsonl")
    reference_hash = _hash(dataset / "references.jsonl")
    run_hashes = {run.name: _hash(run / "predictions.jsonl") for run in run_paths}
    reference_mismatches = []
    for run in run_paths:
        meta = _json((run / "run.json").read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            raise ValueError("run metadata must be a JSON object")
        if "manifest_sha256" not in meta:
            raise ValueError(f"run {run.name}: manifest_sha256 missing")
        if meta["manifest_sha256"] != input_hash:
            raise ValueError(f"run {run.name}: manifest_sha256 mismatch")
        if "reference_manifest_sha256" in meta and meta["reference_manifest_sha256"] != reference_hash:
            reference_mismatches.append(run.name)
        if "output_predictions_sha256" in meta and meta["output_predictions_sha256"] != run_hashes[run.name]:
            raise ValueError(f"run {run.name}: output_predictions_sha256 mismatch")
    score_hashes = {score.name: _validate_score(score, input_hash, reference_hash, run_hashes)
                    for score in score_paths}

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bundle-", dir=output.parent) as tmp:
        base = Path(tmp)
        entries = []
        names = set()
        for source, logical, immutable in files:
            compressed = source.stat().st_size >= compress_threshold
            stored = Path(str(logical) + ".gz") if compressed else logical
            if stored in names:
                raise ValueError(f"duplicate output name: {stored}")
            names.add(stored)
            target = base / stored
            target.parent.mkdir(parents=True, exist_ok=True)
            plain_hash = hashlib.sha256()
            with target.open("xb") as raw:
                writer = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) if compressed else raw
                try:
                    for chunk in _content(source, home, immutable):
                        plain_hash.update(chunk)
                        writer.write(chunk)
                finally:
                    if compressed:
                        writer.close()
            entries.append({"path": stored.as_posix(), "reconstructed_path": logical.as_posix(),
                            "compression": "gzip" if compressed else "none",
                            "stored_sha256": _hash(target), "content_sha256": plain_hash.hexdigest(),
                            "source_sha256": _hash(source), "redacted": not immutable})
        content_hashes = {item["reconstructed_path"]: item["content_sha256"] for item in entries}
        if content_hashes["dataset/inputs.jsonl"] != input_hash or content_hashes["dataset/references.jsonl"] != reference_hash:
            raise ValueError("dataset manifest changed during export")
        for name, digest in run_hashes.items():
            if content_hashes[f"runs/{name}/predictions.jsonl"] != digest:
                raise ValueError(f"run {name}: predictions changed during export")
        for entry in entries:
            if entry["reconstructed_path"].startswith("scores/"):
                name = Path(entry["reconstructed_path"]).name
                if entry["source_sha256"] != score_hashes[name]:
                    raise ValueError(f"score {name}: changed during export")
        image_archive = _image_archive(base, _images(dataset, home, input_hash), input_hash) if include_images else None
        manifest = {
            "format": "ids-benchmark-publication-bundle-v1",
            "image_archive": image_archive,
            "runs_with_other_reference_manifest": reference_mismatches,
            "files": entries,
            "reconstruction": [
                "Decompress each gzip file to its reconstructed_path before using benchmark tools.",
                "Verify stored_sha256 before decompression and content_sha256 afterward.",
                "Inputs, references and predictions retain their original bytes and hashes.",
                "runs_with_other_reference_manifest lists runs that record an earlier or different reference hash; reviewed references may legitimately differ.",
                "Metadata and scores are JSON reserialized with absolute HOME paths replaced by $HOME; source_sha256 identifies the pre-redaction file.",
                ("Verify image_archive.stored_sha256, then extract the archive inside dataset/; "
                 "its paths and byte hashes correspond exactly to the input manifest. "
                 "Image bytes, including embedded metadata, are unredacted. Confirm image licenses before publication."
                 if include_images else "Images are excluded; obtain them separately under their applicable licenses to reproduce inference."),
                "Source fonts and CHISE raw data are excluded; obtain them separately under their applicable licenses to reproduce image generation.",
            ],
        }
        (base / "bundle.json").write_bytes(_encode(manifest))
        # Reserve the destination without replacing an existing directory.
        output.mkdir(exist_ok=False)
        for child in sorted(base.iterdir()):
            os.rename(child, output / child.name)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--score", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-images", action="store_true",
                        help="archive manifest images unchanged; check image licenses and embedded metadata")
    args = parser.parse_args(argv)
    try:
        export(args.dataset, args.run, args.score, args.output, include_images=args.include_images)
    except (OSError, ValueError, UnicodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
