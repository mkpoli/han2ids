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
    assert labels["崢"] == "⿰山爭"


def test_a_character_described_only_with_an_unencoded_component_has_a_label():
    labels = base_labels(ROOT / "data/IDS.TXT", ROOT / "data/label-overrides.tsv")
    assert labels["与"] == "⿹{22}一"
    assert labels["丝"] == "⿱⿰{27}{27}一"


def test_a_sequence_of_encoded_components_is_preferred():
    # BabelStone lists ⿱{88}𠫔 first for 会; the label stays the sequence it had.
    labels = base_labels(ROOT / "data/IDS.TXT", ROOT / "data/label-overrides.tsv")
    assert labels["会"] == "⿱𠆢云"
    assert labels["兆"] == "⿰⿰冫丿⿺乚𡿨"


def test_an_unknown_part_still_leaves_a_character_out():
    # ⿰訁⿱{88}？: the unencoded component is readable, the question mark is not.
    assert "𧪺" not in read(ROOT / "data/IDS.TXT")
