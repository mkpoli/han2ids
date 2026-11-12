import random

import pytest
from PIL import Image, ImageDraw, ImageOps

from han2ids.augmentation import augment


def glyph(size=(80, 100), mode="L"):
    image = Image.new(mode, size, "white")
    draw = ImageDraw.Draw(image)
    draw.line((size[0] // 4, size[1] // 4, size[0] // 4, 3 * size[1] // 4),
              fill="black", width=3)
    draw.line((size[0] // 4, size[1] // 2, 3 * size[0] // 4, size[1] // 2),
              fill="black", width=3)
    return image


def test_same_seed_and_rng_sequence_are_reproducible():
    image = glyph()
    first, second = random.Random(19), random.Random(19)
    for _ in range(5):
        # Global random state must not influence augmentation.
        random.random()
        assert augment(image, first).tobytes() == augment(image, second).tobytes()


def test_different_seeds_vary_placement_and_scale():
    image = glyph()
    results = [augment(image, random.Random(seed)) for seed in range(12)]
    boxes = [ImageOps.invert(result).getbbox() for result in results]
    assert len(set(boxes)) > 4
    assert len({(box[2] - box[0], box[3] - box[1]) for box in boxes}) > 2


@pytest.mark.parametrize("size", [(1, 1), (20, 160), (320, 35), (224, 224), (500, 600)])
@pytest.mark.parametrize("mode", ["L", "RGB", "RGBA"])
def test_output_shape_and_mode_for_varied_inputs(size, mode):
    result = augment(glyph(size, mode), random.Random(8))
    assert result.mode == "L"
    assert result.size == (224, 224)
    assert result.getextrema()[0] < 255


@pytest.mark.parametrize("mode,color", [("L", 255), ("RGB", "white"), ("RGBA", (0, 0, 0, 0))])
def test_blank_images_stay_white(mode, color):
    result = augment(Image.new(mode, (65, 37), color), random.Random(1))
    assert result.getextrema() == (255, 255)


def test_transparency_is_composited_over_white():
    image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((15, 15, 24, 24), fill=(0, 0, 0, 255))
    result = augment(image, random.Random(5))
    assert result.getpixel((0, 0)) == 255
    assert result.getextrema()[0] < 32


def test_ink_on_all_input_edges_is_retained_inside_canvas():
    image = Image.new("L", (100, 100), 255)
    draw = ImageDraw.Draw(image)
    for box in [(0, 0, 9, 9), (90, 0, 99, 9), (0, 90, 9, 99), (90, 90, 99, 99)]:
        draw.rectangle(box, fill=0)
    for seed in range(30):
        result = augment(image, random.Random(seed))
        left, top, right, bottom = ImageOps.invert(result).getbbox()
        assert 0 < left < right < 224 and 0 < top < bottom < 224
        # Four separated corner marks survive even when touching the source edge.
        for x in (left, right - (right - left) // 5):
            for y in (top, bottom - (bottom - top) // 5):
                region = result.crop((x, y, x + (right - left) // 5, y + (bottom - top) // 5))
                assert region.getextrema()[0] < 100


@pytest.mark.parametrize("size,axis", [((100, 10), 1), ((10, 100), 0)])
def test_translation_is_bounded_around_center(size, axis):
    image = Image.new("L", size, 0)
    shifts = []
    for seed in range(60):
        result = augment(image, random.Random(seed))
        left, top, right, bottom = ImageOps.invert(result).getbbox()
        assert left >= 3 and top >= 3 and right <= 221 and bottom <= 221
        center_x = (left + right) / 2
        center_y = (top + bottom) / 2
        # Allow one pixel for bounding-box rounding and blur.
        assert abs(center_x - 112) <= 19
        assert abs(center_y - 112) <= 19
        shifts.append((center_x - 112, center_y - 112)[axis])
    assert min(shifts) < -5 and max(shifts) > 5


def test_augmentation_does_not_mutate_input():
    image = glyph(mode="RGBA")
    original = image.copy()
    augment(image, random.Random(2))
    assert image.mode == original.mode and image.size == original.size
    assert image.tobytes() == original.tobytes()


def test_asymmetric_strokes_keep_their_orientation():
    image = glyph()
    for seed in range(30):
        result = augment(image, random.Random(seed))
        left, top, right, bottom = ImageOps.invert(result).getbbox()
        midpoint = (left + right) // 2
        left_ink = sum(255 - pixel for pixel in result.crop((left, top, midpoint, bottom)).tobytes())
        right_ink = sum(255 - pixel for pixel in result.crop((midpoint, top, right, bottom)).tobytes())
        assert left_ink > right_ink
