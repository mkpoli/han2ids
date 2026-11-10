# han2ids

Read an ideographic description sequence (IDS) from a **Mincho / 宋体** glyph image. One image in,
one sequence out: `⿰𠤕⿱龴疋`.

Scope is deliberately narrow: Mincho and Song serif faces only. Kai, handwriting and sans faces are
out of scope, so the model does not spend capacity on shapes it is not meant to read.

![han2ids v0.3 capability gallery](docs/gallery-v0.3-cover.png)

Status: v0.4, a clean 35.2M model continued from v0.3 on the corrected Noto/IPAmj/Jigmo em-box set. On
the 8,730-row test it reaches 84.54% exact IDS, 87.79% exact-or-same-tree, and 100% valid. v0.3 was
82.88% exact. Noto 93.32%, IPAmj 84.63%, Jigmo 81.80%. See `docs/v0.4-plan.md`, `docs/leak.md` and
`docs/v0.4-results.json`. The v0.1→v0.2 comparison is leaked: 89.9% of current test characters were in
v0.1's training split.

## Install

```sh
uv sync
mkdir -p models
curl -L -o models/han2ids-v0.2.pt \
  https://github.com/mkpoli/han2ids/releases/download/v0.4.0/han2ids-v0.4.pt
```

The checkpoint is 135 MB. It is not committed.

## Use

```sh
uv run han2ids samples/疑.png
```

The default checkpoint is `models/han2ids-v0.3.pt`. Point at another with `--checkpoint`, or set
`HAN2IDS_MODEL`. `--json` prints the IDS, confidence and the chosen preprocessing variant;
`--top-k 3` returns ranked beam alternatives; see `docs/multiple-ids.md`. `--no-tta` uses the em-box render only.

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

The v0.4 checkpoint is attached to the [v0.4.0 release](https://github.com/mkpoli/han2ids/releases/tag/v0.4.0);
the repository does not carry the 135 MB file. [Hugging Face](https://huggingface.co/mkpoli/han2ids-v0.4) mirrors it.

## Training

`scripts/build_dataset.py` renders a font-mixed set from the BabelStone labels.
`scripts/train_fonts_v4.py` trains v0.4 from v0.3; `scripts/train_fonts_v3.py` trains the full v0.3 model; `scripts/train.py` trains from image/label JSONL
directories. `scripts/pilot_fonts.py` is the held-out-font experiment. Nothing uses Kai.

The full v0.3 run used 176,965 images over 95,927 Han characters with a common em-box renderer, four epochs, and evaluated on 8,730 mixed-font rows. See `docs/training.md` for the numbers and the pilot comparison.

## Licence

Code MIT. Fonts and labels keep their own terms; see `NOTICE.md` and `LICENSES/`.
