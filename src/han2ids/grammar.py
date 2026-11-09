"""IDS grammar constraints and greedy decoding."""
from __future__ import annotations

import math

import torch

from .tokenizer import BOS, EOS, PAD

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
    for char in text:
        if not advance(stack, char):
            return False
    return not stack


@torch.no_grad()
def generate(model, images: torch.Tensor, itos: list[str], max_len: int = 48):
    """Greedy decode with the operand-stack mask; returns tokens and geometric mean confidence."""
    model.eval()
    batch, device = images.size(0), images.device
    tokens = torch.full((batch, 1), BOS, dtype=torch.long, device=device)
    stacks = [[1] for _ in range(batch)]
    finished = torch.zeros(batch, dtype=torch.bool, device=device)
    scores = torch.zeros(batch, device=device)
    lengths = torch.zeros(batch, device=device)
    op_ids = torch.tensor([i for i, char in enumerate(itos) if char in ARITY], device=device)
    char_ids = torch.tensor([i for i, char in enumerate(itos) if i >= 4 and char not in ARITY], device=device)
    for step in range(max_len):
        logits = model(images, tokens)[:, -1]
        logprobs = torch.log_softmax(logits.float(), dim=-1)
        mask = torch.full_like(logprobs, float("-inf"))
        for i in range(batch):
            if finished[i] or not stacks[i]:
                mask[i, EOS] = 0
            elif step == 0:
                mask[i, op_ids] = 0
            else:
                mask[i, op_ids] = 0
                mask[i, char_ids] = 0
        masked = logprobs + mask
        choice = masked.argmax(-1)
        scores += masked[torch.arange(batch, device=device), choice]
        lengths += (~finished)
        tokens = torch.cat([tokens, choice[:, None]], 1)
        for i in range(batch):
            if finished[i]:
                continue
            if choice[i] == EOS:
                finished[i] = True
            else:
                advance(stacks[i], itos[choice[i].item()])
        if finished.all():
            break
    confidence = (scores / lengths.clamp(min=1)).exp()
    return tokens[:, 1:], confidence


@torch.no_grad()
def generate_beam(model, image: torch.Tensor, itos: list[str], k: int = 3, max_len: int = 48):
    """Beam search for one image; returns up to k unique (text, confidence) readings."""
    model.eval()
    device = image.device
    op_ids = {i for i, char in enumerate(itos) if char in ARITY}
    char_ids = {i for i, char in enumerate(itos) if i >= 4 and char not in ARITY}
    active = [{"tokens": [BOS], "stack": [1], "score": 0.0, "finished": False}]
    for step in range(max_len):
        candidates = []
        for beam in active:
            if beam["finished"]:
                candidates.append(beam)
                continue
            tokens = torch.tensor([beam["tokens"]], device=device)
            logprobs = torch.log_softmax(model(image, tokens)[0, -1].float(), dim=-1)
            allowed = torch.full_like(logprobs, float("-inf"))
            if not beam["stack"]:
                allowed[EOS] = 0
            elif step == 0:
                allowed[list(op_ids)] = 0
            else:
                allowed[list(op_ids | char_ids)] = 0
            values, indices = (logprobs + allowed).topk(k)
            for value, index in zip(values.tolist(), indices.tolist()):
                stack = list(beam["stack"])
                finished = False
                if index == EOS:
                    finished = True
                    stack = []
                else:
                    advance(stack, itos[index])
                candidates.append({"tokens": beam["tokens"] + [index], "stack": stack,
                                   "score": beam["score"] + value, "finished": finished})
        active = sorted(candidates, key=lambda item: item["score"], reverse=True)[:k]
        if all(beam["finished"] for beam in active):
            break
    out, seen = [], set()
    for beam in sorted(active, key=lambda item: item["score"], reverse=True):
        text = "".join(itos[token] for token in beam["tokens"][1:] if token not in (EOS, PAD))
        if text and text not in seen:
            seen.add(text)
            out.append((text, math.exp(beam["score"] / max(1, len(beam["tokens"]) - 1))))
    return out
