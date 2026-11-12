"""Normalise IDS trees that only differ in how equal-axis operators are nested."""
from __future__ import annotations

from .tokenizer import split

ARITY = {
    "⿰": 2, "⿱": 2, "⿲": 3, "⿳": 3, "⿴": 2, "⿵": 2, "⿶": 2, "⿷": 2,
    "⿸": 2, "⿹": 2, "⿺": 2, "⿻": 2, "⿼": 2, "⿽": 2, "⿾": 1, "⿿": 1,
    "〾": 1, "㇯": 2,
}
VERTICAL = {"⿱", "⿳"}
HORIZONTAL = {"⿰", "⿲"}


def parse(text: list[str], at: int = 0):
    char = text[at]
    if char not in ARITY:
        return char, at + 1
    count = ARITY[char]
    children, at = [], at + 1
    for _ in range(count):
        child, at = parse(text, at)
        children.append(child)
    return (char, tuple(children)), at


def flatten(node):
    if not isinstance(node, tuple):
        return node
    operator, children = node
    children = [flatten(child) for child in children]
    if operator in VERTICAL:
        flat = []
        for child in children:
            if isinstance(child, tuple) and child[0] in VERTICAL:
                flat.extend(child[1])
            else:
                flat.append(child)
        if len(flat) == 3:
            return ("⿳", tuple(flat))
        return ("⿱", tuple(flat))
    if operator in HORIZONTAL:
        flat = []
        for child in children:
            if isinstance(child, tuple) and child[0] in HORIZONTAL:
                flat.extend(child[1])
            else:
                flat.append(child)
        if len(flat) == 3:
            return ("⿲", tuple(flat))
        return ("⿰", tuple(flat))
    return (operator, tuple(children))


def render(node) -> str:
    if not isinstance(node, tuple):
        return node
    return node[0] + ''.join(render(child) for child in node[1])


def normalise(text: str) -> str:
    try:
        tokens = split(text)
        tree, end = parse(tokens)
        if end != len(tokens):
            return text
        return render(flatten(tree))
    except (IndexError, RecursionError):
        return text
