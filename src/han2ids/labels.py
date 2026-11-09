"""Read BabelStone IDS with its region tags and choose the Japanese sequence.

BabelStone lists one sequence per region set. The fonts used by han2ids are Japanese Mincho faces
(Noto Serif CJK JP, IPAmj, Jigmo), so the J-tagged sequence is the one the image is drawn from.
Where no J row exists, the first usable sequence is kept. A small override file handles images the
source cannot describe (for example a Japanese 崢 drawn with 争).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

OPERATORS = set("⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽⿾⿿〾㇯")
LINE = re.compile(r"^U\+([0-9A-F]+)\t(.)\t(.*)$")
SEQUENCE = re.compile(r"\^(.*?)\$(?:\(([A-Z]+)\))?")


@dataclass
class Sequence:
    text: str
    regions: str


def usable(text: str) -> bool:
    return bool(text) and text[0] in OPERATORS and not any(token in text for token in ("{", "&", "？", "?", "[", " "))


def read(path: Path) -> dict[str, list[Sequence]]:
    records: dict[str, list[Sequence]] = {}
    with open(path, encoding="utf-8-sig") as handle:
        for line in handle:
            match = LINE.match(line.rstrip("\n"))
            if not match:
                continue
            char, rest = match.group(2), match.group(3)
            sequences = []
            for text, regions in SEQUENCE.findall(rest):
                if usable(text):
                    sequences.append(Sequence(text, regions or ""))
            if sequences:
                records[char] = sequences
    return records


def choose(sequences: list[Sequence]) -> Sequence:
    for sequence in sequences:
        if "J" in sequence.regions:
            return sequence
    return sequences[0]


def read_overrides(path: Path) -> dict[str, tuple[str, str]]:
    overrides = {}
    if not path.exists():
        return overrides
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        char, text, note = (line.split("\t", 2) + [""])[:3]
        overrides[char] = (text, note)
    return overrides


def base_labels(ids_path: Path, overrides_path: Path) -> dict[str, str]:
    """The first BabelStone sequence, with image-specific overrides."""
    records = read(ids_path)
    overrides = read_overrides(overrides_path)
    return {char: overrides[char][0] if char in overrides else sequences[0].text
            for char, sequences in records.items()}


def japanese_labels(ids_path: Path, overrides_path: Path) -> dict[str, str]:
    """The J-tagged sequence where there is one, for auditing regional variants."""
    records = read(ids_path)
    overrides = read_overrides(overrides_path)
    return {char: overrides[char][0] if char in overrides else choose(sequences).text
            for char, sequences in records.items()}
