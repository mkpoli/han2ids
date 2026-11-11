"""Prepare pinned CHISE source specs without downloading dictionary data.

Retrieve individual URLs listed in chise_sources.json, for example:
    curl --fail --location --output IDS-UCS-Basic.txt \
      https://raw.githubusercontent.com/chise/ids/c3057f890b4d7a990628873f19274ec33b58a7aa/IDS-UCS-Basic.txt

Run: python -m benchmark.prepare_chise --source-dir DIR --output build/chise-specs
The output directory must be new and, inside this repository, gitignored.
For sources under the home directory, output must also be under home so relative
paths do not reveal the home directory name. Spec hashes may therefore vary
with the directory layout even when the pinned dictionary hashes are identical.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


METADATA_PATH = Path(__file__).with_name("chise_sources.json")
REPOSITORY = Path(__file__).resolve().parent.parent


def prepare(source_dir: Path, output: Path, metadata: dict) -> None:
    """Verify all sources and write one spec per source into a new directory."""
    if not isinstance(metadata, dict) or not isinstance(metadata.get("files"), list) or not metadata["files"]:
        raise ValueError("metadata needs a nonempty files list")
    license_name = metadata.get("license")
    if not isinstance(license_name, str) or not license_name.strip():
        raise ValueError("metadata needs a license")
    source_dir = source_dir.resolve(strict=True)
    if not source_dir.is_dir():
        raise ValueError("source directory is not a directory")
    if output.exists() or output.is_symlink():
        raise FileExistsError("output directory already exists")
    output = output.resolve()
    home = Path.home().resolve()
    if source_dir.is_relative_to(home) and not output.is_relative_to(home):
        raise ValueError("output must be under home when sources are under home")
    if output.is_relative_to(REPOSITORY):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", "--", str(output) + "/"],
            cwd=REPOSITORY, check=False,
        )
        if result.returncode not in (0, 1):
            raise ValueError("could not check whether output is ignored by git")
        if result.returncode != 0:
            raise ValueError("output inside the repository must be gitignored")

    entries = []
    seen = set()
    for entry in metadata["files"]:
        if not isinstance(entry, dict):
            raise ValueError("invalid metadata entry")
        name, digest, url = entry.get("name"), entry.get("sha256"), entry.get("url")
        if not isinstance(name, str) or not re.fullmatch(r"IDS-UCS-[A-Za-z0-9-]+\.txt", name):
            raise ValueError("invalid source filename")
        if name in seen:
            raise ValueError(f"duplicate source filename: {name}")
        seen.add(name)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"invalid SHA-256 for {name}")
        if not isinstance(url, str) or not url.startswith("https://") or any(c.isspace() for c in url):
            raise ValueError(f"invalid source URL for {name}")
        source = source_dir / name
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"missing regular source file: {name}")
        with source.open("rb") as handle:
            actual = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                actual.update(chunk)
        if actual.hexdigest() != digest:
            raise ValueError(f"SHA-256 mismatch: {name}")
        entries.append((name, digest, url, source))

    output.mkdir()
    for name, digest, url, source in entries:
        spec = {"path": os.path.relpath(source, output), "sha256": digest,
                "provenance": url, "license": license_name}
        with (output / f"{name}.json").open("x", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False, indent=2)
            handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", type=Path, required=True, help="directory with all pinned dictionary files")
    parser.add_argument("--output", type=Path, required=True, help="new output directory for source specs")
    args = parser.parse_args(argv)
    try:
        metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
        prepare(args.source_dir, args.output, metadata)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
