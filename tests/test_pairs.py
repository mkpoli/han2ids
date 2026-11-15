import importlib.util
import json
from pathlib import Path

import numpy as np
import torch

from han2ids.pairs import PairHead, load

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("train_pairs", ROOT / "scripts/train_pairs.py")
train_pairs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(train_pairs)


def rows(folder: Path, *items: tuple[str, str, dict[str, list[str]]]) -> "train_pairs.Shapes":
    with open(folder / "shapes.jsonl", "w", encoding="utf-8") as out:
        for char, family, sequences in items:
            out.write(json.dumps({"char": char, "family": family, "names": list(sequences), "sequences": sequences,
                                  "regions": []}, ensure_ascii=False) + "\n")
    np.zeros((len(items), train_pairs.SIZE, train_pairs.SIZE), dtype=np.uint8).tofile(folder / "shapes.u8")
    return train_pairs.Shapes(folder)


def test_one_sequence_in_two_families_is_one_form(tmp_path):
    shapes = rows(tmp_path, ("葛", "Jigmo", {"a": ["Adobe-Japan1"]}), ("葛", "NotoSerifCJK-Regular", {"a": ["Adobe-Japan1"]}))
    assert shapes.pairs(["葛"])["same"] == {"葛": [(0, 1)]}


def test_two_sequences_of_one_collection_are_two_forms(tmp_path):
    shapes = rows(tmp_path, ("葛", "Jigmo", {"a": ["Adobe-Japan1"]}), ("葛", "Jigmo", {"b": ["Adobe-Japan1"]}),
                  ("葛", "NotoSerifCJK-Regular", {"b": ["Adobe-Japan1"]}))
    found = shapes.pairs(["葛"])
    assert found["within"] == {"葛": [(0, 1)]}
    assert found["apart"] == {"葛": [(0, 2)]}
    assert found["same"] == {"葛": [(1, 2)]}


def test_sequences_of_different_collections_are_left_out(tmp_path):
    shapes = rows(tmp_path, ("葛", "Jigmo", {"a": ["Adobe-Japan1"]}), ("葛", "ipamjm", {"b": ["Moji_Joho"]}))
    found = shapes.pairs(["葛"])
    assert "葛" not in found["same"] and "葛" not in found["apart"] and "葛" not in found["within"]


def test_a_drawing_without_a_sequence_gives_no_pair(tmp_path):
    shapes = rows(tmp_path, ("葛", "Jigmo", {}), ("葛", "ipamjm", {}))
    assert all("葛" not in found for found in shapes.pairs(["葛"]).values())


def test_characters_two_families_share_are_held_out_first(tmp_path, monkeypatch):
    monkeypatch.setattr(train_pairs, "HELD", 1)
    monkeypatch.setattr(train_pairs, "CHOSEN", 1)
    shapes = rows(
        tmp_path,
        ("一", "Jigmo", {"a": ["Moji_Joho"]}),
        ("二", "Jigmo", {"b": ["Moji_Joho"]}), ("二", "ipamjm", {"b": ["Moji_Joho"]}),
        ("三", "Jigmo", {"c": ["Moji_Joho"]}), ("三", "ipamjm", {"c": ["Moji_Joho"]}),
        ("四", "Jigmo", {"d": ["Moji_Joho"]}), ("四", "ipamjm", {"d": ["Moji_Joho"]}),
    )
    assert shapes.split() == (["二"], ["三"], ["一", "四"])


def test_area_is_the_chance_one_form_scores_higher():
    assert train_pairs.area(np.array([0.9, 0.8]), np.array([0.1, 0.2])) == 1.0
    assert train_pairs.area(np.array([0.9, 0.1]), np.array([0.5, 0.5])) == 0.5


def test_augmenting_keeps_the_frame_and_the_range():
    ink = torch.zeros(3, 1, train_pairs.SIZE, train_pairs.SIZE)
    ink[:, :, 60:160, 100:120] = 1
    out = train_pairs.augment(ink, torch.Generator().manual_seed(1))
    assert out.shape == ink.shape and 0 <= float(out.min()) and float(out.max()) <= 1
    assert float(out.sum()) > 0


def test_the_score_does_not_depend_on_the_order():
    torch.manual_seed(1)
    head = PairHead(8, (11,), patches=4, dim=16, layers=1, heads=2).eval()
    first, second = torch.randn(2, 4, 8), torch.randn(2, 4, 8)
    assert torch.allclose(head.score(first, second), head.score(second, first), atol=1e-6)


def test_a_saved_head_loads_with_its_settings(tmp_path):
    torch.manual_seed(1)
    head = PairHead(8, (5, 11), patches=4, dim=16, layers=1, heads=2).eval()
    torch.save({"head": head.state_dict(), "settings": head.settings}, tmp_path / "pairs.pt")
    again = load(tmp_path / "pairs.pt")
    first, second = torch.randn(1, 4, 16), torch.randn(1, 4, 16)
    assert again.taps == (5, 11)
    assert torch.allclose(again.score(first, second), head.score(first, second))
