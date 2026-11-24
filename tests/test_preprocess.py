import numpy as np
from PIL import Image, ImageDraw

from han2ids.infer import SIZE, _gray, variants


def test_variants_are_square_grayscale():
    image = Image.new("L", (120, 100), 255)
    ImageDraw.Draw(image).rectangle((30, 20, 90, 80), fill=0)
    choices = variants(image)
    assert [name for name, _ in choices] == ["em", "fit 0.03", "fit 0.08", "fit 0.15"]
    for _, picture in choices:
        assert picture.mode == "L"
        assert picture.size == (SIZE, SIZE)


def test_fit_variants_frame_the_ink():
    image = Image.new("L", (400, 400), 255)
    ImageDraw.Draw(image).rectangle((40, 250, 100, 310), fill=0)
    for name, picture in variants(image)[1:]:
        margin = float(name.split()[1])
        box = picture.point(lambda value: 255 if value < 128 else 0).getbbox()
        assert abs(box[0] - SIZE * margin) <= 2 and abs(box[2] - SIZE * (1 - margin)) <= 2


def test_gray_keeps_dense_dark_on_light_glyph():
    # A dense dark-on-light glyph can have overall mean < 127 while its border is white.
    image = Image.new("L", (100, 100), 255)
    ImageDraw.Draw(image).rectangle((8, 8, 91, 91), fill=0)
    assert np.asarray(image).mean() < 127
    result = np.asarray(_gray(image))
    assert result[0, 0] == 255 and result[50, 50] == 0


def test_gray_inverts_light_on_dark_glyph():
    image = Image.new("L", (100, 100), 0)
    ImageDraw.Draw(image).rectangle((25, 25, 74, 74), fill=255)
    result = np.asarray(_gray(image))
    assert result[0, 0] == 255 and result[50, 50] == 0


def test_gray_composites_palette_transparency_over_white():
    palette = Image.new("P", (40, 40), 0)
    palette.putpalette([0, 0, 0, 0, 0, 0] + [0] * 762)
    palette.info["transparency"] = 0
    ImageDraw.Draw(palette).rectangle((10, 10, 29, 29), fill=1)
    result = np.asarray(_gray(palette))
    assert result[0, 0] == 255 and result[20, 20] == 0


def test_gray_preserves_white_glyph_on_transparent_background():
    palette = Image.new("P", (40, 40), 0)
    palette.putpalette([0, 0, 0, 255, 255, 255] + [0] * 762)
    palette.info["transparency"] = 0
    ImageDraw.Draw(palette).rectangle((10, 10, 29, 29), fill=1)
    result = np.asarray(_gray(palette))
    assert result[0, 0] == 255 and result[20, 20] == 0


def test_gray_keeps_tight_cropped_box_outline():
    image = Image.new("L", (16, 16), 255)
    ImageDraw.Draw(image).rectangle((0, 0, 15, 15), outline=0)
    result = np.asarray(_gray(image))
    assert result[0, 0] == 0 and result[8, 8] == 255


def test_gray_handles_empty_image_and_none_transparency():
    empty = Image.new("L", (0, 0), 255)
    assert _gray(empty).size == (0, 0)
    palette = Image.new("P", (16, 16), 0)
    palette.putpalette([255, 255, 255, 0, 0, 0] + [0] * 762)
    palette.info["transparency"] = None
    ImageDraw.Draw(palette).rectangle((4, 4, 11, 11), fill=1)
    result = np.asarray(_gray(palette))
    assert result[0, 0] == 255 and result[8, 8] == 0
