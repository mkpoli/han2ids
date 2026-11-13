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


def test_fit_variants_frame_the_ink():
    image = Image.new("L", (400, 400), 255)
    ImageDraw.Draw(image).rectangle((40, 250, 100, 310), fill=0)
    for name, picture in variants(image)[1:]:
        margin = float(name.split()[1])
        box = picture.point(lambda value: 255 if value < 128 else 0).getbbox()
        assert abs(box[0] - SIZE * margin) <= 2 and abs(box[2] - SIZE * (1 - margin)) <= 2
