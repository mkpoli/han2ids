from PIL import Image, ImageDraw

from han2ids.infer import SIZE, variants


def test_variants_are_square_grayscale():
    image = Image.new("L", (120, 100), 255)
    ImageDraw.Draw(image).rectangle((30, 20, 90, 80), fill=0)
    choices = variants(image)
    assert [name for name, _ in choices] == ["em", "fit 0.03", "fit 0.08", "fit 0.15"]
    for _, picture in choices:
        assert picture.mode == "L"
        assert picture.size == (SIZE, SIZE)
