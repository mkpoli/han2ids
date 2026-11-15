from han2ids.grammar import valid_ids


def test_valid_sequences():
    assert valid_ids("⿰亻五")
    assert valid_ids("⿰𠤕⿱龴疋")
    assert valid_ids("⿳艹罒心")


def test_an_unencoded_component_fills_one_slot():
    assert valid_ids("⿹{22}一")
    assert valid_ids("⿱⿰{27}{27}一")
    assert not valid_ids("{22}")
    assert not valid_ids("⿹{22}")
    assert not valid_ids("⿹{22}一一")


def test_invalid_sequences():
    assert not valid_ids("")
    assert not valid_ids("⿰")
    assert not valid_ids("亻五")
    assert not valid_ids("⿰亻")
