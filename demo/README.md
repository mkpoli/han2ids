# Demo

A one-page reader that runs the int8 ONNX export in the browser. No inference server is involved.

```sh
uv run --extra onnx python scripts/export_onnx.py
uv run python demo/prepare.py
uv run python demo/server.py
```

Open <http://127.0.0.1:8402>. The first read downloads 40.2 MB of int8 models and starts ONNX Runtime
Web in a Web Worker; later reads reuse the sessions. The cut follows the ink automatically, and the
margin slider and handles refine it. The browser build reads one em-box crop, without the CLI's
four-cut beam search, and is the int8 ONNX export, not the canonical PyTorch checkpoint.

## Preprocessing

The cut is automatic; the margin and handles refine it. **Binarise** thresholds a 2× copy of the crop,
starting from Otsu and adjustable with the slider, then downsamples it with smoothing; **Rotate**
turns the input in 90° steps. The **Model input** thumbnail shows the exact grayscale image the model
receives.

## Files

- `server.py` — a local static server for the page.
- `prepare.py` — copies the int8 models from `build/onnx/` and ONNX Runtime Web into `static/`.
- `static/index.html`, `static/app.css`, `static/app.js` — the page, with no build step.
- `static/inference.js`, `static/inference-worker.js` — the Web Worker client and the ONNX decoder.
- `static/i18n.js` — the six UI locales.
- `static/design/` — copies of the IDS Workshop's design system, with provenance in its README.
- `static/fonts/han2ids-glyphs.woff2` — Jigmo subset for sequence text, with provenance in its README.
- `static/samples/sample-yi.png` — the repository's 疑 sample.

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
```
