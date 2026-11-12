# Demo

A one-page reader that runs the int8 ONNX export in the browser. No inference server is involved.

```sh
uv run --extra onnx python scripts/export_onnx.py
uv run python demo/prepare.py
uv run python demo/server.py
```

Open <http://127.0.0.1:8402>. The first read downloads 40.2 MB of int8 models and starts ONNX Runtime
Web in a Web Worker; later reads reuse the sessions. The cut follows the ink automatically and its handles refine it. The page cleans each cut before
reading it; see [Preparation](#preparation). The browser build reads one frame, without the CLI's
four-cut beam search, and is the int8 ONNX export, not the canonical PyTorch checkpoint.

## Files

- `server.py` — a local static server for the page.
- `prepare.py` — copies the int8 models from `build/onnx/` and ONNX Runtime Web into `static/`.
- `make_samples.py` — renders the glyph sheets in `static/samples/`.
- `static/index.html`, `static/app.css`, `static/app.js` — the page and composition root, with no build step.
- `static/theme.js`, `static/language.js`, `static/i18n.js` — theme and language controls.
- `static/files.js`, `static/stage.js`, `static/queue.js` — sources, crop controls and the glyph queue.
- `static/reading.js`, `static/display.js` — reading lifecycle and results.
- `static/prepare.js`, `static/model-input.js` — the frame the model reads, from the cut's pixels.
- `static/benchmark.html`, `static/benchmark.js`, `static/benchmark.css` — the benchmark page, linked from the header.
- `make_benchmark.py` — writes `static/benchmark.json` from the scores in `benchmark/results/`; run it after publishing new scores.
- `static/geometry.js`, `static/identity.js` — crop geometry and generated ids.
- `static/detect.js` — the glyph cut: Otsu ink, connected components, widest-gap splitting.
- `static/ids.js` — the operand-stack grammar, shared by the page and the worker.
- `static/inference.js`, `static/inference-worker.js` — the Web Worker client and the ONNX decoder.
- `static/i18n.js` — the six UI locales.
- `static/design/` — copies of the IDS Workshop's design system, with provenance in its README.
- `static/fonts/han2ids-glyphs.woff2`, `static/fonts/han2ids-forms.woff2` — Jigmo subsets for sequence text, with provenance in their README.
- `static/samples/` — the 疑 sample and the glyph sheets, with provenance in its README.

## Preparation

`prepare.js` turns the cut into the 224 px frame the model reads: black ink on white, upright,
centred with a 12 px margin. It picks the polarity from the border, divides out the paper level cell
by cell, stretches ink and paper to black and white, erases pieces under 2% of the cut's side, and
removes a tilt of up to 12° found from the row and column profiles. The result card and the queue
show that frame. The **Clean up** switch leaves only polarity and framing.

On 60 validation glyphs rendered at 340 px and degraded seven ways, read with the v0.4 fp32 export
(480 images, agreement with the label):

| | clean | paper | blur | tilt | specks | shade | inverted | all seven at once | all |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cut resized to 224 px, 4 px margin | 86.7% | 86.7% | 83.3% | 80.0% | 30.0% | 65.0% | 86.7% | 3.3% | 65.2% |
| prepared | 86.7% | 86.7% | 86.7% | 86.7% | 86.7% | 86.7% | 86.7% | 86.7% | 86.7% |
| without tilt removal | 86.7% | 86.7% | 86.7% | 73.3% | 86.7% | 86.7% | 86.7% | 81.7% | 84.4% |
| without paper division | 86.7% | 86.7% | 86.7% | 86.7% | 86.7% | 75.0% | 86.7% | 55.0% | 81.3% |
| without speck removal | 86.7% | 86.7% | 86.7% | 86.7% | 21.7% | 86.7% | 86.7% | 26.7% | 71.0% |
| without level stretch | 86.7% | 86.7% | 80.0% | 86.7% | 86.7% | 86.7% | 86.7% | 86.7% | 85.8% |

Margins of 8 and 12 px tie; 16 px reads 83.1%, 20 px 81.9% and 32 px 66.9%. Reading two margins and
keeping the more confident one changes nothing. The degradations are synthetic (grey paper with
noise, blur to 130 px, 3–10° tilt, 2–5 px specks, a shading ramp, light on dark), so the table shows
which steps matter and not how real scans will score.

## The cut

`detect.js` binarises the image against its border background, drops specks, then measures the em
box as the longest unbroken run of ink along either axis. The sheet is split at its widest gap,
first into rows and then into glyphs, and never past a piece that already fits one em box, so the
halves of 明, the tiers of 曼 and the strokes of 川 stay together while neighbouring glyphs do not
merge. Two glyphs need one blank pixel row or column between them in at least one direction.

## Locales

The page ships in English, Japanese, Simplified Chinese, Traditional Chinese, Korean and Vietnamese;
the set follows the [IDS Workshop](https://ids.mkpo.li/). The language control is the design system's
select menu from [ids-input#858](https://github.com/mkpoli/ids-input/pull/858). It starts from
`?lang=`, then the saved choice, then the browser language, and stores a change in `han2ids:lang` and
the URL.

## Deploy

```sh
uv run python scripts/build_ocr.py
bunx wrangler@4.158.0 deploy --config deploy/wrangler.ocr.jsonc
```

The Worker serves the static page at `ids.mkpo.li/ocr`. The int8 files are each below the 25 MiB
per-file limit. ONNX Runtime Web is MIT; the model export comes from `scripts/export_onnx.py`.
The unversioned assets require cache revalidation; error responses are not stored.

## Checks

```sh
uv run --extra dev pytest
node demo/check-i18n.mjs
node --test demo/tests/*.test.mjs
node --test deploy/ocr-worker.test.mjs
```

For the optional browser check, see the setup in `check-modules.mjs`.
