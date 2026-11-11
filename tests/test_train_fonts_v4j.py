import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import torch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/train_fonts_v4j.py"
spec = importlib.util.spec_from_file_location("train_fonts_v4j", SCRIPT)
trainer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trainer)


@pytest.fixture
def sample(monkeypatch):
    # Consecutive Jigmo rows are interleaved with other fonts and an OOV label.
    rows = [
        {"char": "a", "font": "noto", "ids": "A"},
        {"char": "b", "font": "jigmo", "ids": "B"},
        {"char": "c", "font": "jigmo", "ids": "?"},
        {"char": "d", "font": "ipamj", "ids": "D"},
        {"char": "e", "font": "jigmo", "ids": "E"},
    ]
    array = np.array([[[0]], [[51]], [[102]], [[153]], [[204]]], dtype=np.uint8)
    vocab = trainer.Vocabulary.from_chars(["A", "B", "D", "E"])
    monkeypatch.setattr(trainer, "gold", lambda char, font, ids: ids)
    return rows, array, vocab


def test_training_keeps_manifest_indices_after_font_and_vocabulary_filters(sample):
    rows, array, vocab = sample
    selected = trainer.select_rows(rows, array)
    dataset = trainer.Rows(selected, array, vocab)
    assert len(dataset) == 2
    for index, (pixel, label) in enumerate([(51, "B"), (204, "E")]):
        image, tokens = dataset[index]
        torch.testing.assert_close(image, torch.full((3, 1, 1), pixel / 255 * 2 - 1))
        assert tokens.tolist() == [trainer.BOS, vocab.stoi[label], trainer.EOS]


def test_evaluation_pairs_selected_images_and_labels_across_batches(sample, monkeypatch):
    rows, array, vocab = sample
    selected = trainer.select_rows(rows, array)
    seen = []

    def generate(model, x, itos):
        pixels = ((x[:, 0, 0, 0] + 1) * 255 / 2).round().int().tolist()
        seen.extend(pixels)
        labels = {51: "B", 102: "B", 204: "E"}
        return torch.tensor([[vocab.stoi[labels[p]], trainer.EOS] for p in pixels]), None

    monkeypatch.setattr(trainer, "generate", generate)
    monkeypatch.setattr(trainer, "valid_ids", lambda text: True)
    model = torch.nn.Identity()
    assert trainer.evaluate(model, selected, array, vocab, batch=2, device="cpu") == (2 / 3, 1.0, 3)
    assert seen == [51, 102, 204]


@pytest.mark.parametrize("split", ["train", "val"])
def test_load_rows_preserves_indices_from_manifest_and_memmap(sample, tmp_path, split):
    rows, array, _ = sample
    (tmp_path / f"{split}.jsonl").write_text("\n".join(map(json.dumps, rows)))
    np.save(tmp_path / f"{split}.npy", array)

    selected, loaded = trainer.load_rows(tmp_path, split)
    assert [index for index, _ in selected] == [1, 2, 4]
    assert [row for _, row in selected] == [rows[1], rows[2], rows[4]]
    assert isinstance(loaded, np.memmap)
    assert loaded[[index for index, _ in selected], 0, 0].tolist() == [51, 102, 204]
    del loaded

    np.save(tmp_path / f"{split}.npy", array[:-1])
    with pytest.raises(ValueError, match="(?i)(rows|manifest).*(array|images)"):
        trainer.load_rows(tmp_path, split)


@pytest.mark.parametrize("length", [4, 6])
def test_rejects_manifest_array_length_mismatch(sample, length):
    rows, array, _ = sample
    bad_array = np.zeros((length, *array.shape[1:]), dtype=np.uint8)
    with pytest.raises(ValueError, match="(?i)(rows|manifest).*(array|images)"):
        trainer.select_rows(rows, bad_array)
