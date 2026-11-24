import math

import pytest
import torch

from han2ids.grammar import generate, generate_beam, generate_beam_batch, valid_ids
from han2ids.tokenizer import BOS, EOS, SPECIALS


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


class StubModel(torch.nn.Module):
    """Minimal encode/decode model with scripted per-step logits for testing decoders."""

    def __init__(self, itos: list[str], logits_fn, max_len: int = 16):
        super().__init__()
        self.itos = itos
        self.logits_fn = logits_fn
        self.max_len = max_len
        self.encode_calls = 0
        self.decode_calls = 0

    def encode(self, images: torch.Tensor) -> torch.Tensor:
        self.encode_calls += 1
        return images

    def decode(self, memory: torch.Tensor, tokens: torch.Tensor) -> torch.Tensor:
        self.decode_calls += 1
        batch, length = tokens.shape
        out = torch.full((batch, length, len(self.itos)), -10.0, device=tokens.device)
        for i in range(batch):
            out[i, -1] = self.logits_fn(memory[i], tokens[i].tolist())
        return out


def test_generate_caches_encoder_and_enforces_budget():
    # Model always prefers binary operator ⿰ over leaves; budget mask must force leaves before max_len.
    itos = SPECIALS + ["⿰", "日", "月"]
    op, sun = itos.index("⿰"), itos.index("日")

    def prefer_op(_mem, _prefix):
        row = torch.full((len(itos),), -5.0)
        row[op] = 5.0
        row[sun] = 1.0
        row[EOS] = 0.0
        return row

    model = StubModel(itos, prefer_op, max_len=6)
    tokens, _ = generate(model, torch.zeros((2, 1)), itos, max_len=6)
    assert model.encode_calls == 1
    for row in tokens.tolist():
        text = "".join(itos[t] for t in row if t not in (0, BOS, EOS))
        assert valid_ids(text)
        assert len(text) <= 5


def test_batched_generate_confidence_matches_single_image():
    # Row 0 finishes in 3 tokens (⿰日月); row 1 takes 5 tokens (⿰日⿰日月).
    itos = SPECIALS + ["⿰", "日", "月"]
    op, sun, moon = itos.index("⿰"), itos.index("日"), itos.index("月")

    def scripted(mem, prefix):
        row = torch.zeros(len(itos))
        step = len(prefix) - 1
        if mem.item() == 0:
            target = [op, sun, moon, EOS][min(step, 3)]
        else:
            target = [op, sun, op, sun, moon, EOS][min(step, 5)]
        row[target] = 4.0
        return row

    model = StubModel(itos, scripted, max_len=12)
    single_tok, single_conf = generate(model, torch.tensor([[0.0]]), itos, max_len=12)
    batch_tok, batch_conf = generate(model, torch.tensor([[0.0], [1.0]]), itos, max_len=12)
    assert batch_conf[0].item() == pytest.approx(single_conf[0].item(), rel=1e-6, abs=1e-6)
    assert single_tok[0].tolist()[:4] == batch_tok[0].tolist()[:4]


def test_beam_batch_caches_encoder_merges_equivalent_trees():
    itos = SPECIALS + ["⿰", "⿲", "木", "日", "月"]
    op2, op3 = itos.index("⿰"), itos.index("⿲")
    wood, sun, moon = itos.index("木"), itos.index("日"), itos.index("月")

    # ⿰木日 finishes at step 3 (prob 0.42); ⿰日⿰月... stays single in active until step 4,
    # then splits into equivalent trees ⿰日⿰月⿲木日月 (0.30) and ⿰日⿰月⿰⿰木日月 (0.28)
    # inside an active beam of k=2.
    def scripted(_mem, prefix):
        row = torch.full((len(itos),), -20.0)
        seq = prefix[1:]
        if not seq:
            row[op2] = 0.0
        elif seq == [op2]:
            row[wood] = math.log(0.42)
            row[sun] = math.log(0.58)
        elif seq == [op2, wood]:
            row[sun] = 0.0
        elif seq == [op2, sun]:
            row[op2] = 0.0
        elif seq == [op2, sun, op2]:
            row[moon] = 0.0
        elif seq == [op2, sun, op2, moon]:
            row[op3] = math.log(30 / 58)
            row[op2] = math.log(28 / 58)
        elif seq == [op2, sun, op2, moon, op2]:
            row[op2] = 0.0
        elif seq in ([op2, sun, op2, moon, op3], [op2, sun, op2, moon, op2, op2]):
            row[wood] = 0.0
        elif seq in ([op2, sun, op2, moon, op3, wood], [op2, sun, op2, moon, op2, op2, wood]):
            row[sun] = 0.0
        elif seq in ([op2, sun, op2, moon, op3, wood, sun], [op2, sun, op2, moon, op2, op2, wood, sun]):
            row[moon] = 0.0
        else:
            row[EOS] = 0.0
        return row

    model = StubModel(itos, scripted, max_len=14)
    raw = generate_beam(model, torch.zeros((1, 1)), itos, k=3, max_len=14, merge=False)
    assert model.encode_calls == 1
    assert [text for text, _ in raw] == ["⿰木日", "⿰日⿰月⿲木日月", "⿰日⿰月⿰⿰木日月"]

    # Even with k=2, merging keeps all completed equivalent paths before pruning to k.
    model.encode_calls = 0
    merged = generate_beam_batch(model, torch.zeros((1, 1)), itos, k=2, max_len=14, merge=True)[0]
    assert model.encode_calls == 1
    assert [text for text, _ in merged] == ["⿰日⿰月⿲木日月", "⿰木日"]
    assert merged[0][1] <= 1.0


def test_merge_keeps_distinct_four_child_trees_separate():
    from han2ids.grammar import _merge_equivalent

    # Both render ambiguously via tree.render(flatten(...)), but have distinct nested tuples.
    merged = _merge_equivalent([("⿰⿰木⿱日月⿰火土", -1.0, 7), ("⿰木⿱⿱日月⿱火土", -1.2, 7)])
    assert [text for text, _ in merged] == ["⿰⿰木⿱日月⿰火土", "⿰木⿱⿱日月⿱火土"]


def test_beam_ensemble_averages_distinct_views():
    itos = SPECIALS + ["⿰", "日", "月", "木"]
    op, sun, moon, wood = itos.index("⿰"), itos.index("日"), itos.index("月"), itos.index("木")

    # View 0 slightly prefers ⿰日月 (0.55 vs 0.45); view 1 strongly prefers ⿰木月 (0.90 vs 0.10).
    def scripted(mem, prefix):
        row = torch.full((len(itos),), -20.0)
        seq = prefix[1:]
        if not seq:
            row[op] = 0.0
        elif seq == [op]:
            if mem.item() == 0:
                row[sun] = math.log(0.55)
                row[wood] = math.log(0.45)
            else:
                row[sun] = math.log(0.10)
                row[wood] = math.log(0.90)
        elif len(seq) == 2:
            row[moon] = 0.0
        else:
            row[EOS] = 0.0
        return row

    model = StubModel(itos, scripted, max_len=8)
    solo = generate_beam_batch(model, torch.tensor([[0.0]]), itos, k=2, max_len=8)[0]
    assert solo[0][0] == "⿰日月"

    model.encode_calls = 0
    ensembled = generate_beam_batch(model, [torch.tensor([[0.0]]), torch.tensor([[1.0]])],
                                    itos, k=2, max_len=8)[0]
    assert model.encode_calls == 1
    assert ensembled[0][0] == "⿰木月"


def test_forced_eos_uses_full_vocab_probability():
    itos = SPECIALS + ["⿰", "日", "月"]
    op, sun, moon = itos.index("⿰"), itos.index("日"), itos.index("月")

    # Model assigns very low logit to EOS even when the tree is complete.
    def low_eos(_mem, prefix):
        row = torch.full((len(itos),), -10.0)
        seq = prefix[1:]
        if not seq:
            row[op] = 10.0
        elif seq == [op]:
            row[sun] = 10.0
        elif seq == [op, sun]:
            row[moon] = 10.0
        else:
            row[sun] = 10.0
            row[EOS] = 0.0
        return row

    model = StubModel(itos, low_eos, max_len=8)
    _, conf = generate(model, torch.zeros((1, 1)), itos, max_len=8)
    assert conf[0].item() < 0.2
