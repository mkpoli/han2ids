# han2ids

Read an ideographic description sequence (IDS) from a **Mincho / 宋体** glyph image. One image in,
one sequence out: `⿰𠤕⿱龴疋`.

Scope is deliberately narrow: Mincho and Song serif faces only. Kai, handwriting and sans faces are
out of scope, so the model does not spend capacity on shapes it is not meant to read.

![han2ids v0.3 capability gallery](docs/gallery-v0.3-cover.png)

Status: v0.5, a 35.2M model continued from v0.4 with printed-form labels, ink-fitted renders and
composed glyphs. On the clean benchmark track (8,730 images of 4,752 held-out characters) v0.5 matches
83.77% of the reference strings exactly, against 80.05% for v0.4. Of those references, 181 have been
checked by a reviewer against the image. See the [benchmark results](benchmark/RESULTS.md),
[protocol](benchmark/PROTOCOL.md) and [leak audit](docs/leak.md): v0.1's training split included 89.9%
of the current test characters.

## Install

```sh
uv sync
mkdir -p models
curl -L -o models/han2ids-v0.5.pt \
  https://github.com/mkpoli/han2ids/releases/download/v0.5.0/han2ids-v0.5.pt
```

The checkpoint is 135 MB. It is not committed.

## Use

```sh
uv run han2ids samples/疑.png
```

The default checkpoint is `models/han2ids-v0.5.pt`. Point at another with `--checkpoint`, or set
`HAN2IDS_MODEL`. Each line gives the reading of the printed form, the unified reading and the
confidence; see `docs/font-variants.md`. `--json` adds the chosen preprocessing variant;
`--top-k 3` returns ranked beam alternatives; see `docs/multiple-ids.md`. `--no-tta` uses the em-box render only.

```console
$ uv run han2ids samples/疑.png samples/字.png
samples/疑.png	⿰𠤕⿱龴疋	⿰𠤕⿱龴疋	0.956
samples/字.png	⿱宀子	⿱宀子	0.940
```

## Demo

```sh
uv run --extra onnx python scripts/export_onnx.py
uv run python demo/prepare.py
uv run python demo/server.py
```

The page at <http://127.0.0.1:8402> runs the int8 ONNX model in a Web Worker; the first read loads
40.2 MB of models. It cleans and frames each cut, then reads it once without the CLI's four-cut beam search, and it is not the
canonical PyTorch checkpoint. See `demo/README.md` for the page and deployment.

## Browser export

```sh
uv run --extra onnx python scripts/export_onnx.py
```

The script writes a split encoder/decoder, an int8 copy, the vocabulary and a manifest to
`build/onnx/`. The int8 pair totals 40.2 MB; both files are under [Cloudflare Pages' 25 MiB
per-file limit](https://developers.cloudflare.com/pages/platform/limits/). The int8 copy matched fp32
on a 200-row test sample. The demo page runs it in a Web Worker with ONNX Runtime Web; the int8
export is not the canonical PyTorch checkpoint.

## Preprocessing

The model reads a 224×224 grayscale image in an em box. A cropped glyph has no em box, so the CLI
tries four placements: the image as given, and the ink fitted at 3%, 8% and 15% margins. It keeps the
reading of the image as given unless that is invalid or a fitted placement scores more than 0.08
above it. v0.5 trained on ink-fitted renders with margins of 6 to 30 px.

## Fonts and data

- [Noto Serif CJK JP](https://github.com/notofonts/noto-cjk), SIL OFL 1.1.
- [IPAmj Mincho](https://moji.or.jp/mojikiban/font/), IPA Font License v1.0. `scripts/fetch_fonts.py`
  downloads Ver.006.01 and checks its MD5.
- [Jigmo](https://kamichikoichi.github.io/jigmo/), CC0 1.0.
- BabelStone IDS labels, public domain, in `data/babelstone-ids.tsv.gz`.

Of the 97,680 Han records, Jigmo covers all 97,680 and IPAmj covers 52,518, adding none. The labels
contain 10,398 distinct characters; Jigmo covers all and IPAmj covers 8,379. IPAmj is useful as a
second Mincho style, not as extra coverage.

The v0.5 checkpoint is attached to the [v0.5.0 release](https://github.com/mkpoli/han2ids/releases/tag/v0.5.0);
the repository does not carry the 135 MB file.

## Training

`scripts/build_dataset.py` renders a font-mixed set from the BabelStone labels.
`scripts/train_v5.py` trains v0.5 from v0.4; `scripts/train_fonts_v4.py` trains v0.4 from v0.3; `scripts/train_fonts_v3.py` trains the full v0.3 model; `scripts/train.py` trains from image/label JSONL
directories. `scripts/pilot_fonts.py` is the held-out-font experiment. Nothing uses Kai.

The full v0.3 run used 176,965 images over 95,927 Han characters with a common em-box renderer, four epochs, and evaluated on 8,730 mixed-font rows. See `docs/training.md` for the numbers and the pilot comparison.

## Licence

Code MIT. Fonts and labels keep their own terms; see `NOTICE.md` and `LICENSES/`.
