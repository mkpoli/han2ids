from __future__ import annotations

import base64
from io import BytesIO

import pytest
from PIL import Image

from demo.server import decode_data_url


def data_url(image: Image.Image, mime: str = "png") -> str:
    buffer = BytesIO()
    image.save(buffer, format=mime.upper())
    return f"data:image/{mime};base64,{base64.b64encode(buffer.getvalue()).decode()}"


def test_decode_data_url_reads_an_image():
    image = Image.new("RGB", (8, 6), "white")
    decoded = decode_data_url(data_url(image))
    assert decoded.size == (8, 6)
    assert decoded.mode == "RGB"


def test_decode_data_url_keeps_transparency():
    image = Image.new("RGBA", (5, 4), (0, 0, 0, 0))
    decoded = decode_data_url(data_url(image))
    assert decoded.size == (5, 4)
    assert decoded.mode == "RGBA"


@pytest.mark.parametrize("value", [
    "",
    "not a data url",
    "data:image/png;base64,!!!",
    "data:image/svg+xml;base64,PHN2Zy8+",
])
def test_decode_data_url_rejects_unsupported_values(value):
    with pytest.raises(ValueError):
        decode_data_url(value)
