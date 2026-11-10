# Demo

A one-page reader for the model: paste or drop a glyph image, adjust the cut, and the page sends the
crop to a local server and shows the IDS.

```sh
uv sync
uv run python demo/server.py
```

Open <http://127.0.0.1:8402>. The server loads the checkpoint once and uses CUDA when it is
available. `--port`, `--checkpoint`, `--host` and `--cpu` are accepted.

The cut follows the ink automatically; the margin slider and the handles refine it. The crop is
sent as a WebP data URL, and the server runs the checkpoint's four preprocessing variants and beam
search for three readings.

## Files

- `server.py` — standard-library HTTP server and the reading endpoint.
- `static/index.html`, `static/app.css`, `static/app.js` — the page, with no build step.
- `static/design/` — copies of the IDS Workshop's design system, with provenance in its README.
- `static/fonts/han2ids-glyphs.woff2` — Jigmo subset for sequence text, with provenance in its README.
- `static/samples/sample-yi.png` — the repository's 疑 sample.

## API

`POST /api/read` takes JSON:

```json
{"image": "data:image/webp;base64,...", "top_k": 3, "tta": true}
```

It returns:

```json
{"readings": [{"ids": "⿰𠤕⿱龴疋", "confidence": 0.9559, "variant": "em", "valid": true}]}
```

`GET /api/health` reports the model version and device.

## Checks

```sh
uv run --extra dev pytest tests/test_demo.py
```
