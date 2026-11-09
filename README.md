# han2ids

Read an ideographic description sequence (IDS) from a **Mincho / 宋体** glyph image. One image in,
one sequence out: `⿰𠤕⿱龴疋`.

Scope is deliberately narrow: Mincho and Song serif faces only. Kai, handwriting and sans faces are
out of scope, so the model does not spend capacity on shapes it is not meant to read.

Status: v0.2, a 35.2M model trained on Noto Serif, IPAmj and the Jigmo family. On the 8,730-row
mixed-font test split it reaches 82.45% exact IDS and 100% valid IDS. On the earlier 4,839-character
synthetic serif split the v0.1 checkpoint reached 80.1%; see `docs/baseline.md` and `docs/training.md`.

## Use

```sh
uv sync
uv run han2ids samples/疑.png
```

The default checkpoint is `models/han2ids-v0.2.pt`. Point at another with `--checkpoint`, or set
`HAN2IDS_MODEL`. `--json` prints the IDS, confidence and the chosen preprocessing variant.
`--no-tta` uses the em-box render only.

```console
$ uv run han2ids samples/疑.png samples/字.png
samples/疑.png	⿰𠤕⿱龴疋	0.91
samples/字.png	⿱宀子	0.96
```

## Preprocessing

The model reads a 224×224 grayscale image in an em box. A cropped glyph has no em box, so the CLI
tries four placements (the image as given, and the ink fitted at 3%, 8% and 15% margins) and keeps
the reading with the highest token confidence. The same augmentation is needed in training before
real crops can be claimed.

## Fonts and data

- [Noto Serif CJK JP](https://github.com/notofonts/noto-cjk), SIL OFL 1.1.
- [IPAmj Mincho](https://moji.or.jp/mojikiban/font/), IPA Font License v1.0. `scripts/fetch_fonts.py`
  downloads Ver.006.01 and checks its MD5.
- [Jigmo](https://kamichikoichi.github.io/jigmo/), CC0 1.0.
- BabelStone IDS labels, public domain, in `data/babelstone-ids.tsv.gz`.

Of the 97,680 Han records, Jigmo covers all 97,680 and IPAmj covers 52,518, adding none. The labels
contain 10,398 distinct characters; Jigmo covers all and IPAmj covers 8,379. IPAmj is useful as a
second Mincho style, not as extra coverage.

The model weights are not in git. Keep `models/han2ids-v0.2.pt` locally; publish it separately when
the checkpoint is ready.

## Training

`scripts/train.py` trains the same architecture from image/label JSONL directories. The serif
training pipeline and the current checkpoint live in the sibling `ids-input` project under
`build/train/`; this repository starts with inference and the font fetcher. Training on IPAmj and
Jigmo renders, with Noto held out, is the next step.

## Licence

Code MIT. Fonts and labels keep their own terms; see `NOTICE.md` and `LICENSES/`.
