"""One classification path for exact, same-tree, regional-variant and miss."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .labels import base_labels
from .tree import normalise

ROOT = Path(__file__).resolve().parents[2]
OPS = set('⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽⿾⿿〾㇯')

GOLD = base_labels(ROOT / 'data/IDS.TXT', ROOT / 'data/label-overrides.tsv')
FONT_GOLD = {}
for line in (ROOT / 'data/font-label-overrides.tsv').read_text().splitlines():
    if line and not line.startswith('#'):
        font, char, text, _ = (line.split('\t') + [''])[:4]
        FONT_GOLD[(char, font)] = text
SAME = {line.split('\t', 1)[0] for line in (ROOT / 'data/equivalence-overrides.tsv').read_text().splitlines() if line and not line.startswith('#')}
VARIANT = {line.split('\t', 1)[0] for line in (ROOT / 'data/variant-overrides.tsv').read_text().splitlines() if line and not line.startswith('#')}

# Replace long strings first. These are regional or design forms, not tree changes.
COMPONENTS = {}
for line in (ROOT / 'data/component-variants.tsv').read_text().splitlines():
    if line and not line.startswith('#'):
        left, right = line.split('\t')[:2]
        COMPONENTS[right] = left
for left, right in [('丹', '⿻⿵冂丨一'), ('半', '⿻八𰀁'), ('鄉', '⿲乡皀阝'),
                    ('徵', '⿲彳⿱山王攵'), ('奏', '𡗗夭')]:
    COMPONENTS[right] = left
ORDERED = sorted(COMPONENTS, key=len, reverse=True)


def gold(char: str, font: str, fallback: str) -> str:
    return FONT_GOLD.get((char, font), GOLD.get(char, fallback))


@lru_cache(None)
def expand(text: str, trail=()) -> str:
    return ''.join(
        char if char in OPS or char not in GOLD or char in trail or len(trail) > 10
        else expand(GOLD[char], trail + (char,))
        for char in text
    )


def variant_form(text: str) -> str:
    for source in ORDERED:
        text = text.replace(source, COMPONENTS[source])
    return text


def same_tree(a: str, b: str) -> bool:
    return normalise(expand(a)) == normalise(expand(b))


def same_variant(a: str, b: str) -> bool:
    if a == b:
        return True
    if variant_form(a) == variant_form(b):
        return True
    return normalise(expand(variant_form(a))) == normalise(expand(variant_form(b)))


def classify(char: str, font: str, pred: str, fallback: str) -> str:
    golden = gold(char, font, fallback)
    if pred == golden:
        return 'exact'
    if char in VARIANT:
        return 'variant'
    if char in SAME or same_tree(pred, golden):
        return 'same'
    if same_variant(pred, golden):
        return 'variant'
    return 'miss'
