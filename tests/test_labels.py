from pathlib import Path

from han2ids.labels import base_labels, choose, read

ROOT = Path(__file__).resolve().parents[1]


def test_japanese_region_sequences():
    records = read(ROOT / "data/IDS.TXT")
    assert choose(records["船"]).text == "⿰舟㕣"
    assert choose(records["勇"]).text == "⿱龴男"


def test_image_overrides():
    labels = base_labels(ROOT / "data/IDS.TXT", ROOT / "data/label-overrides.tsv")
    assert labels["船"] == "⿰舟㕣"
    assert labels["勇"] == "⿱龴男"
    assert labels["屄"] == "⿸尸宂"
    assert labels["崢"] == "⿰山争"
