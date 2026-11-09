from han2ids.grammar import valid_ids


def test_valid_sequences():
    assert valid_ids("⿰亻五")
    assert valid_ids("⿰𠤕⿱龴疋")
    assert valid_ids("⿳艹罒心")


def test_invalid_sequences():
    assert not valid_ids("")
    assert not valid_ids("⿰")
    assert not valid_ids("亻五")
    assert not valid_ids("⿰亻")
