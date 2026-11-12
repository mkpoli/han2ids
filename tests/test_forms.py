from han2ids.grammar import valid_ids
from han2ids.status import classify, gold, unify
from han2ids.tokenizer import Vocabulary, split
from han2ids.tree import normalise

NOTO, IPAMJ, JIGMO = (gold("䦳", font, "") for font in ("noto", "ipamj", "jigmo"))


def test_selector_stays_on_its_base():
    assert split(IPAMJ) == ["⿵", "門", "鄕\U000E0102"]
    assert valid_ids(IPAMJ)
    assert normalise(IPAMJ) == IPAMJ


def test_vocabulary_round_trip():
    vocab = Vocabulary.from_chars(split(IPAMJ))
    assert vocab.decode(vocab.encode(IPAMJ)) == IPAMJ


def test_three_faces_three_forms_one_unified_reading():
    assert len({NOTO, IPAMJ, JIGMO}) == 3
    assert {unify(NOTO), unify(IPAMJ), unify(JIGMO)} == {"⿵門鄉"}


def test_another_form_is_a_variant():
    assert classify("䦳", "ipamj", NOTO, "") == "variant"
    assert classify("䦳", "jigmo", JIGMO, "") == "exact"
