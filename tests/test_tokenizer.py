from han2ids.tokenizer import UNK, Vocabulary, split


def test_an_unencoded_component_is_one_token():
    # BabelStone's, CHISE's and zi.tools' ways of writing a component no code point names.
    assert split("⿹{22}一") == ["⿹", "{22}", "一"]
    assert split("⿰&CDP-8964;口") == ["⿰", "&CDP-8964;", "口"]
    assert split("⿱丿⿹#(-𠃌㇉)一") == ["⿱", "丿", "⿹", "#(-𠃌㇉)", "一"]
    assert split("⿱⿰{27}{27}一") == ["⿱", "⿰", "{27}", "{27}", "一"]


def test_marks_around_anything_else_are_characters():
    assert split("⿰{2口") == ["⿰", "{", "2", "口"]
    assert split("⿰&口") == ["⿰", "&", "口"]
    assert split("{}") == ["{", "}"]
    assert split("{⿱口木}") == ["{", "⿱", "口", "木", "}"]


def test_a_vocabulary_writes_the_component_back():
    vocab = Vocabulary.from_chars(split("⿹{22}一"))
    assert "{22}" in vocab.stoi and "{" not in vocab.stoi
    assert vocab.decode(vocab.encode("⿹{22}一")) == "⿹{22}一"
    # A vocabulary trained without it reads the whole component as one unknown, not four.
    assert Vocabulary.from_chars(split("⿹与一")).encode("⿹{22}一").count(UNK) == 1
