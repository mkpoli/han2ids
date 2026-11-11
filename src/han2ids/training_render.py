"""Bounded font glyph rendering for training images."""

from collections.abc import Mapping
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError
from PIL import Image, ImageChops, ImageDraw, ImageFont


_SIZE = 224
_FONT_SIZE = 200
_CANVAS_SIZE = 1024
_PADDING = 12


class FontRenderer:
    """Render a single covered character from an ordered family of font faces.

    Each face is a (Path, index) pair. Index None selects face zero, including
    for ordinary single-face fonts. Images have black ink on white background.
    """

    def __init__(self, fonts: Mapping[str, list[tuple[Path, int | None]]]):
        if not isinstance(fonts, Mapping) or not fonts:
            raise ValueError("fonts must be a nonempty family mapping")
        self._families = {}
        for family, faces in fonts.items():
            if not isinstance(family, str) or not family:
                raise ValueError("font family must be a nonempty string")
            if not isinstance(faces, list) or not faces:
                raise ValueError(f"family {family!r} must have a nonempty face list")
            checked = []
            for face in faces:
                if not isinstance(face, tuple) or len(face) != 2:
                    raise ValueError("each face must be a (Path, index) tuple")
                path, index = face
                if not isinstance(path, Path) or not path.is_file():
                    raise ValueError(f"font path must be an existing file: {path!r}")
                if index is not None and (type(index) is not int or index < 0):
                    raise ValueError(f"invalid font face index: {index!r}")
                checked.append((path, 0 if index is None else index))
            self._families[family] = tuple(checked)
        self._cmaps = {}
        self._fonts = {}

    def _cmap(self, face):
        if face not in self._cmaps:
            path, index = face
            try:
                with TTFont(path, fontNumber=index, lazy=True) as font:
                    cmap = font.getBestCmap() or {}
                    self._cmaps[face] = frozenset(
                        codepoint for codepoint, glyph in cmap.items() if glyph != ".notdef"
                    )
            except (OSError, TTLibError, ValueError, IndexError) as exc:
                raise ValueError(f"cannot read font cmap {path} face {index}: {exc}") from exc
        return self._cmaps[face]

    def _font(self, face):
        if face not in self._fonts:
            path, index = face
            try:
                self._fonts[face] = ImageFont.truetype(str(path), _FONT_SIZE, index=index)
            except (OSError, ValueError) as exc:
                raise ValueError(f"cannot load font {path} face {index}: {exc}") from exc
        return self._fonts[face]

    def render(self, char: str, family: str) -> Image.Image:
        """Return a padded 224px grayscale glyph, or raise on unsafe input."""
        if not isinstance(char, str) or len(char) != 1 or 0xD800 <= ord(char) <= 0xDFFF:
            raise ValueError("char must be a single Unicode scalar value")
        if not isinstance(family, str) or family not in self._families:
            raise ValueError(f"unknown font family: {family!r}")
        face = next((face for face in self._families[family] if ord(char) in self._cmap(face)), None)
        if face is None:
            raise ValueError(f"no font in family {family!r} covers U+{ord(char):04X}")
        font = self._font(face)
        origin = (_CANVAS_SIZE // 2, _CANVAS_SIZE // 2)
        left, top, right, bottom = font.getbbox(char, anchor="ls")
        if (origin[0] + left <= 0 or origin[1] + top <= 0
                or origin[0] + right >= _CANVAS_SIZE or origin[1] + bottom >= _CANVAS_SIZE):
            raise ValueError(f"glyph U+{ord(char):04X} exceeds the rendering canvas")
        canvas = Image.new("L", (_CANVAS_SIZE, _CANVAS_SIZE), 255)
        ImageDraw.Draw(canvas).text(origin, char, fill=0, font=font, anchor="ls")
        bbox = ImageChops.invert(canvas).getbbox()
        if bbox is None:
            raise ValueError(f"glyph U+{ord(char):04X} has no ink")
        left, top, right, bottom = bbox
        if left == 0 or top == 0 or right == _CANVAS_SIZE or bottom == _CANVAS_SIZE:
            raise ValueError(f"glyph U+{ord(char):04X} touches the rendering canvas boundary")
        glyph = canvas.crop(bbox)
        width, height = glyph.size
        scale = (_SIZE - 2 * _PADDING) / max(width, height)
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        glyph = glyph.resize(size, Image.Resampling.LANCZOS)
        output = Image.new("L", (_SIZE, _SIZE), 255)
        output.paste(glyph, ((_SIZE - size[0]) // 2, (_SIZE - size[1]) // 2))
        if ImageChops.invert(output).getbbox() is None:
            raise ValueError(f"glyph U+{ord(char):04X} has no ink after resizing")
        return output
