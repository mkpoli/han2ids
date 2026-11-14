"""Name the registered form of a character that a glyph image draws.

The candidates of a character are the character alone, each variation sequence a font's cmap carries
for it, and its compatibility ideographs, drawn in every face that maps them. Labels come from
IVD_Sequences.txt, StandardizedVariants.txt, the Unicode decompositions and each font's own name and
cmap tables. The image and the candidates are compared by the checkpoint's encoder; see
docs/variant-match.md for the measurements behind the comparison and the thresholds.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont, ImageOps, features

from .forms import unify
from .infer import _gray, tensor
from .tokenizer import selector

ROOT = Path(__file__).resolve().parents[2]
SIZE, MARGIN = 224, 12
# docs/variant-match.md: below FLOOR nothing is close. The shapes that answer are within MARGIN of the best
# score, or within RATIO times the best's own distance from 1 when that is less.
FLOOR, MARGIN_OF_BEST, RATIO = 0.93, 0.03, 2.0
IVD_LINE = re.compile(r"^([0-9A-F]+) (E01[0-9A-F]{2}); ([^;]+); (.+)$")
STANDARDIZED_LINE = re.compile(r"^([0-9A-F]+) (FE0[0-9A-F]); CJK COMPATIBILITY IDEOGRAPH-([0-9A-F]+);")
REGION = re.compile(r"\bCJK (JP|KR|SC|TC|HK)$")

FONTS = [
    ROOT / "cache/fonts/jigmo/Jigmo.ttf",
    ROOT / "cache/fonts/jigmo/Jigmo2.ttf",
    ROOT / "cache/fonts/jigmo/Jigmo3.ttf",
    ROOT / "cache/fonts/ipamj/ipamjm.ttf",
    Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
]
SEQUENCES = ROOT / "cache/ivd/IVD_Sequences-2026-08-03.txt"
STANDARDIZED = ROOT / "cache/ucd/StandardizedVariants-17.0.0.txt"


def registrations(path: Path) -> dict[tuple[int, int], list[list[str]]]:
    """Each registered pair of base and selector with its collections and identifiers."""
    pairs: dict[tuple[int, int], list[list[str]]] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = IVD_LINE.match(line)
        if match:
            pairs.setdefault((int(match.group(1), 16), int(match.group(2), 16)), []).append(
                [match.group(3).strip(), match.group(4).strip()])
    return pairs


def standardized(path: Path) -> dict[tuple[int, int], int]:
    """Each standardized variation sequence of a CJK compatibility ideograph, with that ideograph."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return {(int(match.group(1), 16), int(match.group(2), 16)): int(match.group(3), 16)
            for match in map(STANDARDIZED_LINE.match, lines) if match}


def compatibility() -> dict[int, list[int]]:
    """The compatibility ideographs of each unified ideograph, from the canonical decompositions."""
    out: dict[int, list[int]] = {}
    for point in [*range(0xF900, 0xFB00), *range(0x2F800, 0x2FA20)]:
        target = unicodedata.decomposition(chr(point))
        if target and " " not in target and not target.startswith("<"):
            out.setdefault(int(target, 16), []).append(point)
    return out


def fit(part: Image.Image) -> Image.Image:
    """A crop of the ink, centred on white with the clean track's margin."""
    scale = (SIZE - 2 * MARGIN) / max(part.size)
    part = part.resize((max(1, round(part.width * scale)), max(1, round(part.height * scale))),
                       Image.Resampling.LANCZOS)
    out = Image.new("L", (SIZE, SIZE), 255)
    out.paste(part, ((SIZE - part.width) // 2, (SIZE - part.height) // 2))
    return out


def frame(font, text: str) -> Image.Image | None:
    """The text's ink in the clean track's frame, or None when nothing is drawn."""
    canvas = Image.new("L", (448, 448), 255)
    ImageDraw.Draw(canvas).text((224, 300), text, font=font, fill=0, anchor="ms")
    box = ImageOps.invert(canvas).getbbox()
    return fit(canvas.crop(box)) if box else None


def framed(image: Image.Image) -> Image.Image | None:
    """An image's ink in the frame the candidates are drawn in."""
    base = _gray(image)
    box = base.point(lambda value: 255 if value < 220 else 0).getbbox()
    return fit(base.crop(box)) if box else None


def code(text: str) -> str:
    return " ".join(f"U+{ord(char):04X}" for char in text)


@dataclass(frozen=True)
class Candidate:
    """One drawing of one name: a character or sequence in a face."""
    char: str
    kind: str  # plain, ivs, standardized or compatibility
    text: str
    registrations: tuple[tuple[str, str], ...]
    font: str
    face: str | None
    compatibility: str | None = None

    @property
    def sequence(self) -> str:
        return code(self.text)

    @property
    def name(self) -> str:
        """What the candidate names, whatever face draws it; a standardized sequence names its ideograph."""
        return self.compatibility or self.sequence

    def label(self) -> dict:
        out = {"kind": self.kind, "sequence": self.sequence, "text": self.text,
               "registrations": [{"collection": collection, "identifier": identifier}
                                 for collection, identifier in self.registrations]}
        if self.compatibility:
            out["compatibility"] = self.compatibility
        return out

    def record(self) -> dict:
        return {**self.label(), "font": self.font, "face": self.face}


@dataclass
class Shape:
    """Every candidate that one font file draws with the same pixels."""
    image: Image.Image
    file: str
    index: int
    candidates: list[Candidate] = field(default_factory=list)

    @cached_property
    def regions(self) -> list[str]:
        """The regional faces that draw the character alone this way."""
        return [item.face for item in self.candidates if item.kind == "plain" and item.face]

    @cached_property
    def labels(self) -> dict[str, dict]:
        """What the shape names: its sequences and compatibility ideographs, or else its regional design.

        A font's own drawing of the character with neither names nothing.
        """
        out: dict[str, dict] = {}
        for item in self.candidates:
            if item.kind != "plain":
                out.setdefault(item.name, item.label())
        if not out and self.regions:
            plain = self.candidates[0]
            out[f"{plain.sequence} {' '.join(self.regions)}"] = {**plain.label(), "regions": self.regions}
        return out

    @property
    def names(self) -> list[str]:
        return list(self.labels)


class Face:
    def __init__(self, path: Path, index: int, table):
        self.path, self.index = Path(path), index
        names = table["name"]
        self.font = names.getDebugName(4) or names.getDebugName(1) or self.path.stem
        region = REGION.search(names.getDebugName(1) or "")
        self.region = region.group(1) if region else None
        self.cmap = {point for point, glyph in (table.getBestCmap() or {}).items() if glyph != ".notdef"}
        self.selectors: dict[int, list[int]] = {}
        for sub in table["cmap"].tables:
            if sub.format == 14:
                for mark, entries in sub.uvsDict.items():
                    for base, _ in entries:
                        self.selectors.setdefault(base, []).append(mark)

    @cached_property
    def pen(self):
        return ImageFont.truetype(str(self.path), SIZE, index=self.index, layout_engine=ImageFont.Layout.RAQM)


def faces(path: Path) -> list[Face]:
    """Every face of a font file, named and placed by the file's own tables."""
    from fontTools.ttLib import TTCollection, TTFont
    with open(path, "rb") as handle:
        collection = handle.read(4) == b"ttcf"
    if not collection:
        return [Face(path, 0, TTFont(path, lazy=True))]
    return [Face(path, index, table) for index, table in enumerate(TTCollection(path, lazy=True).fonts)]


class Forms:
    """The candidate forms of a character, drawn from a set of font files."""

    def __init__(self, fonts: list[Path] | None = None, sequences: Path | None = None,
                 standardized_variants: Path | None = None):
        if not features.check("raqm"):
            raise RuntimeError("Pillow has no RAQM layout, which variation sequences need")
        paths = [Path(path) for path in fonts] if fonts is not None else [path for path in FONTS if path.is_file()]
        if not paths:
            raise FileNotFoundError("no font to draw candidates with; see docs/variant-match.md")
        self.faces = [face for path in paths for face in faces(path)]
        sequences = SEQUENCES if sequences is None else Path(sequences)
        self.registered = registrations(sequences) if sequences.is_file() else {}
        table = STANDARDIZED if standardized_variants is None else Path(standardized_variants)
        self.standardized = standardized(table) if table.is_file() else {}
        self.compatibility = compatibility()
        self._shapes: dict[str, list[Shape]] = {}

    def labels(self, char: str, face: Face) -> list[tuple[str, str, tuple, str | None]]:
        """What a face draws for a character: kind, text, registrations and compatibility ideograph."""
        base = ord(char)
        out: list[tuple[str, str, tuple, str | None]] = []
        if base in face.cmap:
            out.append(("plain", char, (), None))
        for mark in sorted(face.selectors.get(base, [])):
            if 0xE0100 <= mark <= 0xE01EF:
                listed = tuple(tuple(item) for item in self.registered.get((base, mark), []))
                out.append(("ivs", char + chr(mark), listed, None))
            elif (base, mark) in self.standardized:
                out.append(("standardized", char + chr(mark), (), f"U+{self.standardized[(base, mark)]:04X}"))
        for other in self.compatibility.get(base, []):
            if other in face.cmap:
                out.append(("compatibility", chr(other), (), None))
        return out

    def shapes(self, char: str) -> list[Shape]:
        """The distinct drawings of a character, each with every name and face that draws it."""
        if char not in self._shapes:
            found: dict[tuple[str, str], Shape] = {}
            for face in self.faces:
                for kind, text, listed, compat in self.labels(char, face):
                    image = frame(face.pen, text)
                    if image is None:
                        continue
                    ink = np.packbits(np.asarray(image) < 128).tobytes()
                    shape = found.setdefault((str(face.path), hashlib.sha256(ink).hexdigest()),
                                             Shape(image, str(face.path), face.index))
                    shape.candidates.append(Candidate(char, kind, text, listed, face.font, face.region, compat))
            self._shapes[char] = list(found.values())
        return self._shapes[char]


def decide(scored: list[tuple[float, Shape]], floor: float = FLOOR, margin: float = MARGIN_OF_BEST,
           ratio: float = RATIO) -> tuple[str, str | None, list[Shape]]:
    """The verdict, its reason and the shapes that answer, from shapes ranked by score."""
    if not scored:
        return "none", "no-candidate", []
    best = scored[0][0]
    if best < floor:
        return "none", "no-close-form", []
    reach = min(margin, ratio * max(0.0, 1 - best))
    near = [shape for score, shape in scored if score >= best - reach]
    names = {name for shape in near for name in shape.names}
    if len(names) < 2:
        return "matched", None, near
    shared = any(names <= set(shape.names) for shape in near)
    return "ambiguous", "identical-shape" if shared else "close-shapes", near


@dataclass
class Match:
    chars: list[str]
    verdict: str  # matched, ambiguous or none
    reason: str | None
    ranked: list[tuple[float, Shape]]
    answer: list[Shape]

    @property
    def labels(self) -> list[dict]:
        """Each name in the answer; the character alone when the answer's shapes name nothing."""
        found: dict[str, dict] = {}
        for shape in self.answer:
            for name, label in shape.labels.items():
                found.setdefault(name, label)
        if self.answer and not found:
            plain = self.answer[0].candidates[0]
            return [{"kind": "plain", "sequence": code(plain.char), "text": plain.char, "registrations": []}]
        return list(found.values())

    @property
    def regions(self) -> list[str]:
        """The regional faces whose own drawing of the character is in the answer."""
        return list(dict.fromkeys(region for shape in self.answer for region in shape.regions))

    def record(self) -> dict:
        answer = {id(shape) for shape in self.answer}
        return {
            "chars": self.chars, "verdict": self.verdict, "reason": self.reason,
            "labels": self.labels, "regions": self.regions,
            "shapes": [{"score": round(score, 4), "answer": id(shape) in answer,
                        "candidates": [item.record() for item in shape.candidates]}
                       for score, shape in self.ranked],
        }

    def line(self) -> str:
        """The verdict and the answer's names for the tab-separated output."""
        def name(label: dict) -> str:
            notes = [f"{item['collection']} {item['identifier']}" for item in label["registrations"]]
            notes += [label["compatibility"]] if "compatibility" in label else []
            notes += label.get("regions", [])
            return f"{label['sequence']} ({', '.join(notes)})" if notes else label["sequence"]
        return f"{self.verdict}\t{'; '.join(name(label) for label in self.labels)}"


class Characters:
    """The characters a reading can name, from every BabelStone sequence."""

    def __init__(self, ids: Path = ROOT / "data/IDS.TXT"):
        from .labels import read
        self.named: dict[str, list[str]] = {}
        for char, sequences in read(ids).items():
            for sequence in sequences:
                self.named.setdefault(sequence.text, []).append(char)

    def __call__(self, reading: str) -> list[str]:
        plain = "".join(char for char in reading if not selector(char))
        if len(plain) == 1:
            return [plain]
        found = [*self.named.get(reading, []), *self.named.get(plain, []), *self.named.get(unify(reading), [])]
        return list(dict.fromkeys(found))


class VariantMatcher:
    """Rank the candidate forms of a character against an image, with the reader's encoder."""

    def __init__(self, reader, forms: Forms | None = None, floor: float = FLOOR, margin: float = MARGIN_OF_BEST,
                 ratio: float = RATIO):
        self.reader, self.forms = reader, forms or Forms()
        self.floor, self.margin, self.ratio = floor, margin, ratio
        self._vectors: dict[int, np.ndarray] = {}

    @cached_property
    def characters(self) -> Characters:
        return Characters()

    @torch.no_grad()
    def embed(self, images: list[Image.Image], batch: int = 64) -> np.ndarray:
        """The mean of the encoder's patch tokens for each image, at unit length."""
        out = []
        for start in range(0, len(images), batch):
            pixels = torch.stack([tensor(image) for image in images[start:start + batch]]).to(self.reader.device)
            encoder = self.reader.model.encoder
            patches = encoder.forward_features(pixels)[:, encoder.num_prefix_tokens:]
            out.append(torch.nn.functional.normalize(patches.mean(1).float(), dim=1).cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, 1), dtype=np.float32)

    def vectors(self, shapes: list[Shape]) -> np.ndarray:
        missing = [shape for shape in shapes if id(shape) not in self._vectors]
        for shape, vector in zip(missing, self.embed([shape.image for shape in missing])):
            self._vectors[id(shape)] = vector
        return np.stack([self._vectors[id(shape)] for shape in shapes])

    def match(self, image: Image.Image, chars: str | list[str]) -> Match:
        """The forms of the given characters ranked against the image, and the verdict."""
        chars = list(dict.fromkeys(chars))
        shapes = [shape for char in chars for shape in self.forms.shapes(char)]
        query = framed(image)
        if not shapes or query is None:
            return Match(chars, "none", "no-candidate", [], [])
        scores = self.vectors(shapes) @ self.embed([query])[0]
        ranked = sorted(zip(map(float, scores), shapes), key=lambda pair: -pair[0])
        verdict, reason, answer = decide(ranked, self.floor, self.margin, self.ratio)
        return Match(chars, verdict, reason, ranked, answer)

    def match_reading(self, image: Image.Image, reading: str) -> Match:
        """The match for the characters a reading names, or none when it names no character."""
        chars = self.characters(reading)
        if not chars:
            return Match([], "none", "no-character", [], [])
        return self.match(image, chars)
