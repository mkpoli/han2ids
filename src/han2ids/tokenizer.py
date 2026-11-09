"""The character vocabulary written by the model."""
from __future__ import annotations

PAD, BOS, EOS, UNK = 0, 1, 2, 3
SPECIALS = ["<pad>", "<bos>", "<eos>", "<unk>"]


class Vocabulary:
    def __init__(self, itos: list[str]):
        self.itos = itos
        self.stoi = {char: index for index, char in enumerate(itos)}

    def __len__(self) -> int:
        return len(self.itos)

    @classmethod
    def from_chars(cls, chars: list[str]) -> "Vocabulary":
        return cls(SPECIALS + sorted(chars))

    def encode(self, text: str, max_len: int = 48) -> list[int]:
        ids = [BOS] + [self.stoi.get(char, UNK) for char in text] + [EOS]
        return ids[:max_len]

    def decode(self, ids: list[int]) -> str:
        out = []
        for token in ids:
            if token == EOS:
                break
            if token in (PAD, BOS):
                continue
            out.append(self.itos[token])
        return "".join(out)
