from han2ids.tree import normalise


def test_vertical_stack():
    assert normalise("⿱⿱⺈𠔿比") == normalise("⿳⺈𠔿比")


def test_horizontal_stack():
    assert normalise("⿰⿰人一二") == normalise("⿲人一二")
