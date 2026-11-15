from han2ids.tree import normalise


def test_vertical_stack():
    assert normalise("⿱⿱⺈𠔿比") == normalise("⿳⺈𠔿比")


def test_horizontal_stack():
    assert normalise("⿰⿰人一二") == normalise("⿲人一二")


def test_an_unencoded_component_is_a_leaf():
    assert normalise("⿱⿱{88}一二") == normalise("⿳{88}一二")
    assert normalise("⿹{22}一") == "⿹{22}一"
