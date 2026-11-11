from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFont

from han2ids.training_render import FontRenderer


@pytest.fixture
def han_font():
    for path in (
        Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
        Path('/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc'),
        Path('/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'),
    ):
        if path.is_file():
            return path
    pytest.skip('no suitable installed Han font')


@pytest.fixture
def latin_font():
    path = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    if not path.is_file():
        pytest.skip('DejaVu Sans is not installed')
    return path


@pytest.mark.parametrize('char', ['漢', '龍', '一', '龜'])
def test_full_ink_is_centered_and_padded(han_font, char):
    renderer = FontRenderer({'han': [(han_font, 0)]})
    # Independently draw the complete glyph on a large baseline-anchored canvas.
    font = ImageFont.truetype(str(han_font), 200, index=0)
    canvas = Image.new('L', (1024, 1024), 255)
    ImageDraw.Draw(canvas).text((512, 512), char, font=font, fill=0, anchor='ls')
    ink_box = ImageChops.invert(canvas).getbbox()
    assert ink_box is not None
    left, top, right, bottom = ink_box
    assert 0 < left < right < 1024 and 0 < top < bottom < 1024
    ink = canvas.crop(ink_box)
    scale = 200 / max(ink.size)
    expected_size = tuple(max(1, round(n * scale)) for n in ink.size)
    expected = Image.new('L', (224, 224), 255)
    expected.paste(ink.resize(expected_size, Image.Resampling.LANCZOS),
                   ((224 - expected_size[0]) // 2, (224 - expected_size[1]) // 2))

    result = renderer.render(char, 'han')
    assert result.mode == 'L' and result.size == (224, 224)
    assert ImageChops.difference(result, expected).getbbox() is None
    left, top, right, bottom = ImageChops.invert(result).getbbox()
    assert min(left, top, 224 - right, 224 - bottom) >= 12


def test_old_renderer_clips_real_glyph(han_font):
    font = ImageFont.truetype(str(han_font), 224, index=0)
    canvas = Image.new('L', (600, 600), 255)
    ImageDraw.Draw(canvas).text((300, 300), '漢', font=font, fill=0, anchor='ms')
    left, top, right, bottom = ImageChops.invert(canvas).getbbox()
    # The previous renderer cropped x=origin±100 and y=baseline-176..baseline+24.
    assert left < 200 or right > 400 or top < 124 or bottom > 324
    result = FontRenderer({'han': [(han_font, 0)]}).render('漢', 'han')
    assert ImageChops.invert(result).getbbox() is not None


def test_first_covering_face_and_caches(han_font, latin_font, monkeypatch):
    import han2ids.training_render as module

    opened, loaded = [], []
    real_ttfont, real_truetype = module.TTFont, module.ImageFont.truetype

    def ttfont(path, *args, **kwargs):
        opened.append((path, kwargs['fontNumber']))
        return real_ttfont(path, *args, **kwargs)

    def truetype(path, *args, **kwargs):
        loaded.append((Path(path), kwargs['index']))
        return real_truetype(path, *args, **kwargs)

    monkeypatch.setattr(module, 'TTFont', ttfont)
    monkeypatch.setattr(module.ImageFont, 'truetype', truetype)
    renderer = FontRenderer({'mixed': [(latin_font, None), (han_font, 0)],
                             'same': [(han_font, 0)]})
    renderer.render('漢', 'mixed')
    renderer.render('龍', 'same')
    renderer.render('A', 'mixed')
    assert opened == [(latin_font, 0), (han_font, 0)]
    assert loaded == [(han_font, 0), (latin_font, 0)]


def test_ttc_face_index_is_used(han_font, monkeypatch):
    if han_font.suffix.lower() != '.ttc':
        pytest.skip('no font collection available')
    import han2ids.training_render as module

    calls = []
    real_truetype = module.ImageFont.truetype

    def truetype(path, size, **kwargs):
        calls.append((Path(path), size, kwargs['index']))
        return real_truetype(path, size, **kwargs)

    monkeypatch.setattr(module.ImageFont, 'truetype', truetype)
    image = FontRenderer({'han': [(han_font, 1)]}).render('漢', 'han')
    assert ImageChops.invert(image).getbbox() is not None
    assert calls == [(han_font, 200, 1)]


def test_first_covering_blank_glyph_does_not_fall_back(han_font, latin_font, monkeypatch):
    renderer = FontRenderer({'mixed': [(latin_font, 0), (han_font, 0)]})
    loaded = []
    original = renderer._font

    def font(face):
        loaded.append(face)
        return original(face)

    monkeypatch.setattr(renderer, '_font', font)
    with pytest.raises(ValueError, match='no ink'):
        renderer.render(' ', 'mixed')
    assert loaded == [(latin_font, 0)]


def test_missing_and_blank_coverage_fails(han_font):
    renderer = FontRenderer({'han': [(han_font, 0)]})
    with pytest.raises(ValueError, match='covers'):
        renderer.render('\U0010ffff', 'han')
    with pytest.raises(ValueError, match='no ink'):
        renderer.render(' ', 'han')


def test_boundary_ink_fails(han_font, monkeypatch):
    def draw_boundary(self, xy, text, *args, **kwargs):
        self.point((0, 100), fill=0)
    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', draw_boundary)
    with pytest.raises(ValueError, match='boundary'):
        FontRenderer({'han': [(han_font, 0)]}).render('漢', 'han')


def test_outside_metrics_fail(han_font, monkeypatch):
    class OversizedFont:
        def getbbox(self, char, anchor):
            return (-600, 0, 1, 1)

    renderer = FontRenderer({'han': [(han_font, 0)]})
    monkeypatch.setattr(renderer, '_font', lambda face: OversizedFont())
    with pytest.raises(ValueError, match='exceeds'):
        renderer.render('漢', 'han')


@pytest.mark.parametrize('char', ['', 'ab', '\ud800', None, 1])
def test_invalid_char_fails(han_font, char):
    with pytest.raises(ValueError, match='single Unicode'):
        FontRenderer({'han': [(han_font, 0)]}).render(char, 'han')


def test_invalid_families_and_faces(han_font, tmp_path):
    for fonts in (None, {}, {'': [(han_font, 0)]}, {'han': []},
                  {'han': [(str(han_font), 0)]}, {'han': [(tmp_path / 'missing', 0)]},
                  {'han': [(han_font, -1)]}, {'han': [(han_font, True)]},
                  {'han': [(han_font, '0')]}, {'han': [han_font]}):
        with pytest.raises(ValueError):
            FontRenderer(fonts)
    renderer = FontRenderer({'han': [(han_font, 0)]})
    with pytest.raises(ValueError, match='unknown font family'):
        renderer.render('漢', 'missing')
    bad_font = tmp_path / 'invalid.ttf'
    bad_font.write_bytes(b'not a font')
    with pytest.raises(ValueError, match='cannot read font cmap'):
        FontRenderer({'bad': [(bad_font, 0)]}).render('漢', 'bad')
    with pytest.raises(ValueError, match='cannot read font cmap'):
        FontRenderer({'bad': [(han_font, 9999)]}).render('漢', 'bad')
