# Pair comparison

A head over the reader's patch tokens scores whether two glyph images draw one registered form. It
is trained on pairs that variation collections decide, and separates forms a stroke apart that the
[variant match](variant-match.md) scores as one. The variant match does not use it yet.

## Run

```sh
uv sync --extra variants
uv run python scripts/fetch_fonts.py
curl --create-dirs -o cache/ivd/IVD_Sequences-2026-08-03.txt https://www.unicode.org/ivd/data/2026-08-03/IVD_Sequences.txt
curl --create-dirs -o cache/ucd/StandardizedVariants-17.0.0.txt https://www.unicode.org/Public/17.0.0/ucd/StandardizedVariants.txt
uv run --extra variants python scripts/train_pairs.py draw --output build/pairs
uv run --extra variants python scripts/train_pairs.py train --output build/pairs --run head
uv run --extra variants python scripts/train_pairs.py measure --output build/pairs --run head
```

`draw` writes 3.9 GB of drawings. `train` holds them in memory, takes about 2 GB of GPU memory and ran
8,000 steps in 23 minutes on an RTX 5070 Ti shared with another job. `measure` writes
`measure.json` and `pairs.jsonl.gz` beside the head.

From Python:

```python
import torch
from han2ids.infer import Han2IDS, tensor
from han2ids.pairs import load, patch_tokens
from han2ids.variants import framed

reader = Han2IDS("models/han2ids-v0.5.pt")
head = load("build/pairs/head/pairs.pt", reader.device)
pixels = torch.stack([tensor(framed(image)) for image in (first, second)]).to(reader.device)
tokens = patch_tokens(reader.model.encoder, pixels, head.taps)
head.score(tokens[:1], tokens[1:])  # the probability of one form
```

## Pairs

The drawings are the variant match's candidates: every character of `IVD_Sequences.txt` in Jigmo,
IPAmj Mincho and the five faces of Noto Serif CJK Regular, 76,998 distinct drawings of 15,304
characters.

| Pair | Label | Training pairs | Characters |
| --- | --- | ---: | ---: |
| One sequence drawn by two font families | one form | 22,677 | 12,487 |
| A drawing and itself, each printed differently | one form | 44,230 | 13,302 |
| Two sequences of one collection, in two families | two forms | 18,303 | 4,486 |
| Two sequences of one collection, in one family | two forms | 19,173 | 5,738 |
| Two characters | two forms | at random | |

A collection registers a design once, so two of its sequences are two forms. Two sequences of
different collections can be one design under two names; such pairs are left out. A batch takes
30% of its pairs from the first row, 15%, 20%, 25% and 10% from the next, a character at random and
then one of its pairs. Both drawings of a training pair vary in stroke weight, scale, slant, place,
resolution and blur.

The 1,500 characters of the variant match's sample are held out, and the next 500 of the same
order choose the checkpoint; the other 13,304 train.

## Head

The reader's encoder is frozen. Its patch tokens after blocks 6, 9 and 12, each through the final
norm, are joined per patch and projected to 256 dimensions. A two-layer transformer reads a class
token and the 196 tokens of each image, and the class token gives the logit. The score is the
sigmoid of the mean logit of both orders. The head has 1.9 million weights.

Training is 8,000 steps of 128 pairs with AdamW at 3e-4, a 500-step warm-up and a cosine decay.
Every 500 steps the head ranks the 898 pairs of one form against the 780 of two among the 500
characters; the checkpoint is the step with the highest area, step 7,000 at 0.984.
[`log-v0.5.json`](pair-comparison/log-v0.5.json) has every step measured.

## Measurements

The tables report the 750 held-out characters at odd positions; the even ones set each scorer's
level, the score that refuses 1% of the right candidates. The queries are the variant match's:
one family's drawing of a sequence against another family's drawings of the character.
[`measure-v0.5.json`](pair-comparison/measure-v0.5.json) holds the counts and
[`pairs-v0.5.jsonl.gz`](pair-comparison/pairs-v0.5.jsonl.gz) every pair with both scores.

| | Cosine of mean patch tokens | Cosine at the 0.93 floor | Head | Head above the floor |
| --- | ---: | ---: | ---: | ---: |
| Level | 0.922 | 0.930 | 0.055 | 0.055 |
| Best candidate right, 2,667 queries | 2,503 (93.9%) | 2,503 (93.9%) | 2,557 (95.9%) | 2,555 (95.8%) |
| Right candidate refused, 2,667 queries | 16 (0.6%) | 30 (1.1%) | 10 (0.4%) | 40 (1.5%) |
| One form in two families refused, 1,341 pairs | 9 (0.7%) | 16 (1.2%) | 6 (0.4%) | 22 (1.6%) |
| Two forms of one collection taken as one, 980 pairs | 546 (55.7%) | 485 (49.5%) | 133 (13.6%) | 92 (9.4%) |
| Area: one form ranked above two | 0.905 | 0.905 | 0.978 | 0.972 |

"Head above the floor" takes a pair only when the cosine reaches 0.93 and the head reaches its
level, which is how the variant match would apply it.

The variant match's control keeps only the candidates of forms the query's own font draws
differently, so no right answer is left. A query counts when one of them reaches the level:

| Nearest other form in the query's font | Queries | Cosine | Cosine at the floor | Head | Head above the floor |
| --- | ---: | ---: | ---: | ---: | ---: |
| all | 1,400 | 870 (62.1%) | 781 (55.8%) | 238 (17.0%) | 173 (12.4%) |
| under 0.90 | 220 | 1 (0.5%) | 1 (0.5%) | 10 (4.5%) | 0 (0.0%) |
| 0.90 to 0.95 | 368 | 131 (35.6%) | 75 (20.4%) | 36 (9.8%) | 14 (3.8%) |
| 0.95 and over | 812 | 738 (90.9%) | 705 (86.8%) | 192 (23.6%) | 159 (19.6%) |

These candidates include sequences of other collections than the query's, which can be the
query's own design under another name; the pairs of one collection in the first table have no such
case.

A head that reads only the final block names the right candidate less often than the cosine and
takes more forms as one ([`measure-v0.5-last-block.json`](pair-comparison/measure-v0.5-last-block.json)):

| Tokens read | Area | Best candidate right | Two forms taken as one, 980 pairs | Control, 1,400 queries |
| --- | ---: | ---: | ---: | ---: |
| Blocks 6, 9 and 12 | 0.978 | 2,557 (95.9%) | 133 (13.6%) | 238 (17.0%) |
| Block 12 | 0.940 | 2,473 (92.7%) | 337 (34.4%) | 539 (38.5%) |

## Limits

- The measured queries are clean drawings from the three training families. Scans and other
  typefaces are not measured.
- Of the 133 pairs still taken as one, three of the six looked at show no difference larger than
  the two fonts' own. Nobody has sorted the 133 into those and real misses.
- The head alone takes 10 of 220 queries whose nearest other form is far in the cosine; under the
  cosine floor it takes none.
- One run of each setting was made, with one seed.

## Sources

The fonts and Unicode files are those of the [variant match](variant-match.md#sources), with the
same editions and hashes. The head of these measurements has SHA-256
`f3841defeb388100e4ba0ff71da84096507961c15a8b52a12acbdffeb05fddb4`; it was trained on
`han2ids-v0.5.pt` and is not published.
