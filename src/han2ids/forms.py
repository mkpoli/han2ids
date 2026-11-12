"""Printed forms of a component and the unified reading that folds them together."""
from __future__ import annotations

from pathlib import Path

from .tokenizer import selector, split

UNIFIED: dict[str, str] = {}
for line in (Path(__file__).with_name("unified-forms.tsv")).read_text(encoding="utf-8").splitlines():
    if line and not line.startswith("#"):
        form, unified = line.split("\t")[:2]
        UNIFIED[form] = unified


def unify(text: str) -> str:
    """The reading with each printed form replaced by the component that stands for it."""
    return "".join(UNIFIED.get(token) or "".join(char for char in token if not selector(char))
                   for token in split(text))
