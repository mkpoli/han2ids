# Demo

A one-page reader that runs the int8 ONNX export in the browser. No inference server is involved.

```sh
uv run --extra onnx python scripts/export_onnx.py
uv run python demo/prepare.py
uv run python demo/server.py
```

Open <http://127.0.0.1:8402>. The first read downloads 40.2 MB of int8 models and starts ONNX Runtime
Web in a Web Worker; later reads reuse the sessions. A sheet of glyphs is cut into one item per
glyph, each read on its own; the margin slider and the handles refine the cut of the selected item,
and the review panel holds the final sequence, a note and a status. The browser build reads one
em-box crop per item, without the CLI's four-crop ensemble, and is the int8 ONNX export, not the
canonical PyTorch checkpoint.

## The decoder

`inference-worker.js` runs the same operand-stack grammar as `src/han2ids/grammar.py`: an operator
first, a token for every open slot, and `EOS` only once the stack is empty. It searches a beam of
five, scores each reading as the geometric mean of its token probabilities, drops duplicates and
ranks by that score. On this machine one 224 px crop takes about 0.8 s against 0.35 s for a single
beam; the four glyphs of `sheet-grid.png` read in 5.2 s including the model load. The score is
uncalibrated, and no accuracy figure measured on the PyTorch checkpoint carries over to this build.

## Files

- `server.py` — a local static server for the page.
- `prepare.py` — copies the int8 models from `build/onnx/` and ONNX Runtime Web into `static/`.
- `make_samples.py` — renders the glyph sheets in `static/samples/`.
- `static/index.html`, `static/app.css`, `static/app.js` — the page, with no build step.
- `static/detect.js` — the glyph cut: Otsu ink, connected components, widest-gap splitting.
- `static/ids.js` — the operand-stack grammar, shared by the page and the worker.
- `static/store.js` — the IndexedDB copy of the review set: images, crops, readings and status.
- `static/inference.js`, `static/inference-worker.js` — the Web Worker client and the ONNX decoder.
- `static/i18n.js` — the six UI locales.
- `static/design/` — copies of the IDS Workshop's design system, with provenance in its README.
- `static/fonts/han2ids-glyphs.woff2` — Jigmo subset for sequence text, with provenance in its README.
- `static/samples/` — the 疑 sample and the glyph sheets, with provenance in its README.

## The cut

`detect.js` binarises the image against its border background, drops specks, then measures the em
box as the longest unbroken run of ink along either axis. The sheet is split at its widest gap,
first into rows and then into glyphs, and never past a piece that already fits one em box, so the
halves of 明, the tiers of 曼 and the strokes of 川 stay together while neighbouring glyphs do not
merge. Two glyphs need one blank pixel row or column between them in at least one direction.

## The review set

Items, source images, crops, readings, the final sequence, the note and the status live in one
implicit local project in IndexedDB (`han2ids-ocr`), restored on the next visit and emptied by
Clear. Export JSON writes the same fields, versioned, through a Blob download. Nothing leaves the
browser.

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

## Checks

```sh
uv run --extra dev pytest
node demo/check-i18n.mjs
node --test demo/check-stale-reading.mjs
node demo/check-detect.mjs
```
