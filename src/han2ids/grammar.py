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
