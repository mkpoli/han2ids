"""IDS grammar constraints, cached greedy decoding, and batched beam search."""
from __future__ import annotations

import math

import torch

from .tokenizer import BOS, EOS, PAD, split
from .tree import flatten, parse

ARITY = {
    "⿰": 2, "⿱": 2, "⿲": 3, "⿳": 3, "⿴": 2, "⿵": 2, "⿶": 2, "⿷": 2,
    "⿸": 2, "⿹": 2, "⿺": 2, "⿻": 2, "⿼": 2, "⿽": 2, "㇯": 2,
    "⿾": 1, "⿿": 1, "〾": 1,
}


def advance(stack: list[int], char: str) -> bool:
    """Fill one operand slot and push an operator's operands."""
    while stack and stack[-1] == 0:
        stack.pop()
    if not stack:
        return False
    stack[-1] -= 1
    if char in ARITY:
        stack.append(ARITY[char])
    while stack and stack[-1] == 0:
        stack.pop()
    return True


def valid_ids(text: str) -> bool:
    if not text or text[0] not in ARITY:
        return False
    stack = [1]
    for char in split(text):
        if len(char) > 1 and char[0] in ARITY:
            return False
        if not advance(stack, char):
            return False
    return not stack


def _token_arities(itos: list[str], device: torch.device) -> torch.Tensor:
    return torch.tensor([ARITY.get(char, 0) if i >= 4 else 0 for i, char in enumerate(itos)],
                        dtype=torch.long, device=device)


def grammar_mask(logits: torch.Tensor, slots: torch.Tensor, arities: torch.Tensor,
                 step: int, remaining: int) -> torch.Tensor:
    """Mask logits to tokens that keep the prefix tree valid and finishable within remaining steps."""
    vocab_size = logits.size(-1)
    done = slots.eq(0)
    legal = torch.zeros_like(logits, dtype=torch.bool)
    legal[:, EOS] = done
    fits = (slots[:, None] + arities[None, :] - 1) <= remaining
    if step == 0:
        candidates = (arities[None, :] > 0) & fits
    else:
        token_ids = torch.arange(vocab_size, device=logits.device)[None, :]
        candidates = (token_ids >= 4) & fits
    legal |= (~done)[:, None] & candidates
    empty = ~legal.any(dim=-1)
    if empty.any():
        legal[empty, EOS] = True
    return logits.float().masked_fill(~legal, float("-inf"))


def _tree_key(text: str):
    try:
        tokens = split(text)
        parsed, end = parse(tokens)
        if end == len(tokens):
            return flatten(parsed)
    except (IndexError, RecursionError):
        pass
    return text


def _merge_equivalent(candidates: list[tuple[str, float, int]]) -> list[tuple[str, float]]:
    """Merge beam candidates that share the same flattened IDS tree by summing probability mass."""
    groups: dict[object, tuple[str, float, int]] = {}
    for text, score, length in candidates:
        key = _tree_key(text)
        if key not in groups:
            groups[key] = (text, score, length)
        else:
            rep_text, old_score, rep_len = groups[key]
            hi = max(old_score, score)
            merged = hi + math.log(math.exp(old_score - hi) + math.exp(score - hi))
            groups[key] = (rep_text, merged, rep_len)
    ordered = sorted(groups.values(), key=lambda item: item[1], reverse=True)
    return [(text, math.exp(score / max(1, length))) for text, score, length in ordered]


@torch.no_grad()
def generate(model, images: torch.Tensor, itos: list[str], max_len: int = 48):
    """Greedy decode with cached encoder features and budget-aware grammar masking."""
    model.eval()
    batch, device = images.size(0), images.device
    limit = min(max_len, getattr(model, "max_len", max_len))
    cached = hasattr(model, "encode") and hasattr(model, "decode")
    memory = model.encode(images) if cached else None
    arities = _token_arities(itos, device)
    tokens = torch.full((batch, 1), BOS, dtype=torch.long, device=device)
    slots = torch.ones(batch, dtype=torch.long, device=device)
    finished = torch.zeros(batch, dtype=torch.bool, device=device)
    scores = torch.zeros(batch, device=device)
    lengths = torch.zeros(batch, device=device)
    for step in range(limit):
        logits = (model.decode(memory, tokens) if cached else model(images, tokens))[:, -1]
        logprobs = grammar_mask(torch.log_softmax(logits.float(), dim=-1),
                                slots, arities, step, remaining=limit - step - 2)
        choice = logprobs.argmax(-1)
        step_scores = logprobs[torch.arange(batch, device=device), choice]
        scores += torch.where(finished, torch.zeros_like(step_scores), step_scores)
        lengths += (~finished)
        tokens = torch.cat([tokens, choice[:, None]], 1)
        newly_done = choice.eq(EOS)
        delta = torch.where((~finished) & (~newly_done) & (choice >= 4), arities[choice] - 1, 0)
        slots = slots + delta
        finished |= newly_done
        if finished.all():
            break
    confidence = (scores / lengths.clamp(min=1)).exp()
    return tokens[:, 1:], confidence


@torch.no_grad()
def generate_beam_batch(model, images: torch.Tensor | list[torch.Tensor] | tuple[torch.Tensor, ...],
                        itos: list[str], k: int = 5, max_len: int = 48,
                        merge: bool = False) -> list[list[tuple[str, float]]]:
    """Batched beam search with cached encoding, budget masking, and optional view ensembling."""
    if k < 1:
        raise ValueError("k must be positive")
    model.eval()
    views = list(images) if isinstance(images, (list, tuple)) else [images]
    if not views:
        raise ValueError("images must not be empty")
    batch, device = views[0].size(0), views[0].device
    limit = min(max_len, getattr(model, "max_len", max_len))
    cached = hasattr(model, "encode") and hasattr(model, "decode")
    if cached:
        if len(views) == 1:
            memories = [model.encode(views[0])]
        else:
            memories = list(model.encode(torch.cat(views, dim=0)).split(batch, dim=0))
    else:
        memories = None
    arities = _token_arities(itos, device)
    arity_list = arities.tolist()
    active: list[list[tuple[list[int], float, int]]] = [[([BOS], 0.0, 1)] for _ in range(batch)]
    finished: list[list[tuple[list[int], float]]] = [[] for _ in range(batch)]
    for step in range(limit):
        pairs = [(i, hyp) for i, hyps in enumerate(active) for hyp in hyps]
        if not pairs:
            break
        owners = torch.tensor([i for i, _ in pairs], dtype=torch.long, device=device)
        seq = torch.tensor([hyp[0] for _, hyp in pairs], dtype=torch.long, device=device)
        slots = torch.tensor([hyp[2] for _, hyp in pairs], dtype=torch.long, device=device)
        remaining = limit - step - 2
        dists = []
        if cached:
            for memory in memories:
                logits = model.decode(memory[owners], seq)[:, -1]
                dists.append(grammar_mask(torch.log_softmax(logits.float(), dim=-1),
                                          slots, arities, step, remaining))
        else:
            for view in views:
                logits = model(view[owners], seq)[:, -1]
                dists.append(grammar_mask(torch.log_softmax(logits.float(), dim=-1),
                                          slots, arities, step, remaining))
        logprobs = dists[0] if len(dists) == 1 else torch.logsumexp(torch.stack(dists), 0) - math.log(len(dists))
        values, indices = logprobs.topk(min(k, logprobs.size(-1)), dim=-1)
        candidates: list[list[tuple[list[int], float, int]]] = [[] for _ in range(batch)]
        for (i, (prefix, score, missing)), vs, ixs in zip(pairs, values.tolist(), indices.tolist()):
            for value, index in zip(vs, ixs):
                if not math.isfinite(value):
                    continue
                total = score + value
                if index == EOS:
                    finished[i].append((prefix + [EOS], total))
                else:
                    candidates[i].append((prefix + [index], total, missing + arity_list[index] - 1))
        for i in range(batch):
            active[i] = sorted(candidates[i], key=lambda item: item[1], reverse=True)[:k]
            if not merge:
                finished[i] = sorted(finished[i], key=lambda item: item[1], reverse=True)[:k]
                if len(finished[i]) >= k and (not active[i] or finished[i][-1][1] >= active[i][0][1]):
                    active[i] = []

    results: list[list[tuple[str, float]]] = []
    for i in range(batch):
        pool = finished[i] or [(prefix, score) for prefix, score, _ in active[i]]
        raw: list[tuple[str, float, int]] = []
        seen: set[str] = set()
        for seq_ids, score in sorted(pool, key=lambda item: item[1], reverse=True):
            text = "".join(itos[token] for token in seq_ids[1:] if token not in (EOS, PAD))
            if text and text not in seen:
                seen.add(text)
                raw.append((text, score, max(1, len(seq_ids) - 1)))
        if merge:
            results.append(_merge_equivalent(raw)[:k])
        else:
            results.append([(text, math.exp(score / length)) for text, score, length in raw[:k]])
    return results


@torch.no_grad()
def generate_beam(model, image: torch.Tensor, itos: list[str], k: int = 3, max_len: int = 48,
                  merge: bool = False):
    """Beam search for one image; returns up to k unique (text, confidence) readings."""
    return generate_beam_batch(model, image, itos, k=k, max_len=max_len, merge=merge)[0]
