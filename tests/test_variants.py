from pathlib import Path

import pytest
from PIL import Image

from han2ids import variants
from han2ids.variants import Candidate, Characters, Forms, Shape, VariantMatcher, decide

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "models/han2ids-v0.5.pt"
JIGMO, IPAMJ, NOTO = variants.FONTS[0], variants.FONTS[3], variants.FONTS[4]


def shape(*texts: str, face: str | None = None) -> Shape:
    blank = Image.new("L", (1, 1), 255)
    return Shape(blank, "font", 0, [Candidate(text[0], "ivs" if len(text) > 1 else "plain", text, (), "Font", face)
                                    for text in texts])


def test_one_close_name_is_matched():
    verdict, reason, answer = decide([(0.97, shape("葛\U000E0100")), (0.93, shape("葛\U000E0101"))])
    assert (verdict, reason) == ("matched", None)
    assert [item.names for item in answer] == [["U+845B U+E0100"]]


def test_two_fonts_drawing_one_name_are_matched():
    verdict, _, answer = decide([(0.97, shape("葛", "葛\U000E0100")), (0.96, shape("葛\U000E0100"))])
    assert verdict == "matched" and len(answer) == 2


def test_a_font_default_without_a_name_does_not_compete():
    verdict, _, answer = decide([(0.97, shape("葛\U000E0100")), (0.96, shape("葛"))])
    assert verdict == "matched" and len(answer) == 2


def test_a_regional_design_competes():
    verdict, reason, answer = decide([(0.97, shape("葛\U000E0100")), (0.96, shape("葛", face="SC"))])
    assert (verdict, reason) == ("ambiguous", "close-shapes")
    assert answer[1].names == ["U+845B SC"]


def test_names_sharing_a_shape_are_ambiguous():
    verdict, reason, _ = decide([(0.97, shape("葛\U000E0100", "葛\U000E0103")), (0.90, shape("葛\U000E0101"))])
    assert (verdict, reason) == ("ambiguous", "identical-shape")


def test_shapes_within_the_margin_are_ambiguous():
    verdict, reason, answer = decide([(0.97, shape("葛\U000E0100")), (0.95, shape("葛\U000E0101")), (0.90, shape("葛"))])
    assert (verdict, reason) == ("ambiguous", "close-shapes")
    assert len(answer) == 2


def test_an_exact_drawing_is_held_to_itself():
    scored = [(0.998, shape("葛\U000E0100")), (0.975, shape("葛\U000E0101"))]
    assert decide(scored)[0] == "matched"
    assert decide(scored, ratio=1e9)[0] == "ambiguous"
    assert decide([(1.0000001, shape("葛\U000E0100"))])[2]


def test_nothing_close_is_none():
    assert decide([(0.80, shape("葛\U000E0100"))])[:2] == ("none", "no-close-form")
    assert decide([])[:2] == ("none", "no-candidate")


def test_a_reading_names_its_characters():
    named = Characters()
    assert named("⿱宀子") == ["字"]
    assert named("鄕\U000E0102") == ["鄕"]
    assert named("⿱⿱⿱⿱一一一一一") == []


@pytest.fixture(scope="module")
def forms():
    pytest.importorskip("fontTools", reason="the variants extra is not installed")
    for path in [*variants.FONTS, variants.SEQUENCES, variants.STANDARDIZED]:
        if not path.is_file():
            pytest.skip(f"{path} is absent")
    return Forms()


def drawing(forms: Forms, text: str, font: Path, face: str | None = None) -> Image.Image:
    return next(item.image for item in forms.shapes(text[0]) if item.file == str(font)
                and any(candidate.text == text and face in (None, candidate.face) for candidate in item.candidates))


def test_candidates_carry_the_registrations(forms):
    found = {candidate.text: candidate for item in forms.shapes("葛") for candidate in item.candidates}
    assert found["葛\U000E0100"].registrations == (("Adobe-Japan1", "CID+1481"),)
    assert found["葛\U000E0103"].registrations == (("Hanyo-Denshi", "FT1769"), ("Moji_Joho", "MJ022336"))
    assert found["葛\U000E0100"].record()["sequence"] == "U+845B U+E0100"
    found = {candidate.text: candidate for item in forms.shapes("鄕") for candidate in item.candidates}
    assert found["鄕\U000E0102"].registrations == (("Hanyo-Denshi", "IP9115"), ("Moji_Joho", "MJ026366"))


def test_regional_faces_come_from_the_font_names(forms):
    regions = {face.region: face.index for face in forms.faces if face.region}
    assert regions == {"JP": 0, "KR": 1, "SC": 2, "TC": 3, "HK": 4}
    plain = {candidate.face for item in forms.shapes("葛") for candidate in item.candidates if candidate.kind == "plain"}
    assert {"JP", "KR", "SC", "TC", "HK"} <= plain


def test_a_compatibility_ideograph_is_a_candidate(forms):
    kinds = {(candidate.kind, candidate.name) for item in forms.shapes("著") for candidate in item.candidates}
    assert ("compatibility", "U+FA5F") in kinds
    assert ("standardized", "U+FA5F") in kinds


@pytest.fixture(scope="module")
def reader():
    if not CHECKPOINT.is_file():
        pytest.skip(f"{CHECKPOINT} is absent")
    from han2ids.infer import Han2IDS
    return Han2IDS(CHECKPOINT, device="cpu")


def names(match) -> list[str]:
    return [label["sequence"] for label in match.labels]


def test_a_form_is_matched_across_fonts(forms, reader):
    others = VariantMatcher(reader, Forms(fonts=[IPAMJ, NOTO]))
    match = others.match(drawing(forms, "源\U000E0102", JIGMO), "源")
    assert (match.verdict, match.reason) == ("matched", None)
    assert match.labels == [{"kind": "ivs", "sequence": "U+6E90 U+E0102", "text": "源\U000E0102", "registrations": [
        {"collection": "Hanyo-Denshi", "identifier": "JTB45D"}, {"collection": "Moji_Joho", "identifier": "MJ059789"}]}]
    assert match.ranked[0][0] < 0.99


def test_sequences_one_font_draws_alike_are_ambiguous(forms, reader):
    match = VariantMatcher(reader, forms).match(drawing(forms, "鄕", JIGMO), "鄕")
    assert (match.verdict, match.reason) == ("ambiguous", "identical-shape")
    assert names(match) == ["U+9115 U+E0100", "U+9115 U+E0101"]


def test_葛_in_its_own_font_is_matched(forms, reader):
    matcher = VariantMatcher(reader, forms)
    first = matcher.match(drawing(forms, "葛\U000E0100", NOTO), "葛")
    assert (first.verdict, names(first)) == ("matched", ["U+845B U+E0100"])
    second = matcher.match(drawing(forms, "葛\U000E0101", NOTO), "葛")
    assert (second.verdict, names(second), second.regions) == ("matched", ["U+845B U+E0101"], ["JP", "KR"])
    regional = matcher.match(drawing(forms, "葛", NOTO, "SC"), "葛")
    assert (regional.verdict, regional.labels[0]["kind"], regional.regions) == ("matched", "plain", ["SC"])


def test_葛_from_another_font_lists_the_forms_alike(forms, reader):
    others = VariantMatcher(reader, Forms(fonts=[IPAMJ, NOTO]))
    match = others.match(drawing(forms, "葛\U000E0100", JIGMO), "葛")
    assert (match.verdict, match.reason) == ("ambiguous", "close-shapes")
    assert set(names(match)) == {"U+845B U+E0100", "U+845B U+E0102", "U+845B U+E0107"}


def test_another_character_is_none(forms, reader):
    match = VariantMatcher(reader, forms).match(drawing(forms, "鄕", NOTO), "葛")
    assert (match.verdict, match.reason, match.labels) == ("none", "no-close-form", [])


def test_the_record_is_stable(forms, reader):
    record = VariantMatcher(reader, forms).match(drawing(forms, "葛\U000E0100", NOTO), "葛").record()
    assert list(record) == ["chars", "verdict", "reason", "labels", "regions", "shapes"]
    assert list(record["shapes"][0]) == ["score", "answer", "candidates"]
    assert list(record["shapes"][0]["candidates"][0]) == ["kind", "sequence", "text", "registrations", "font", "face"]
    assert list(record["labels"][0]) == ["kind", "sequence", "text", "registrations"]
    assert record["shapes"][0]["score"] == pytest.approx(1.0, abs=5e-3)


def test_the_plain_read_does_not_load_the_matcher():
    import subprocess
    import sys
    check = "import sys, han2ids.cli; sys.exit('han2ids.variants' in sys.modules or 'fontTools' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", check], cwd=ROOT / "src").returncode == 0
