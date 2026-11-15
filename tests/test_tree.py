from han2ids.tokenizer import split
from han2ids.tree import normalise, parse


def test_vertical_stack():
    assert normalise("⿱⿱⺈𠔿比") == normalise("⿳⺈𠔿比")


def test_horizontal_stack():
    assert normalise("⿰⿰人一二") == normalise("⿲人一二")


def test_an_unencoded_component_is_a_leaf():
    assert parse(split("⿹{22}一"))[0] == ("⿹", ("{22}", "一"))
    assert normalise("⿱⿱{88}一二") == "⿳{88}一二"
