# Glyph benchmark preparation

Run from the repository root with Python 3.10+, Pillow, fontTools and NumPy. The source JSONL requires one `char` code point, `ids`, and `font` per row. Row order is preserved; row indexes are zero-based. Each font argument names a source `font`, an explicit collection face index and a file. Repeat a family to specify its ordered coverage candidates. The first candidate whose Unicode cmap maps the character to a non-`.notdef` glyph is used. A missing glyph, empty image or unresolved clipping aborts the run without publishing an output directory.

Example, using a small prefix of the original test set (replace font paths with your own):

```sh
python -m benchmark.generate \
  --manifest "$HOME/projects/Philology/han2ids/build/font-v03/test.jsonl" \
  --original-array "$HOME/projects/Philology/han2ids/build/font-v03/test.npy" \
  --out /tmp/han2ids-benchmark-small \
  --font 'noto=0=/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc' \
  --font "ipamj=0=$HOME/projects/Philology/han2ids/cache/fonts/ipamj/ipamjm.ttf" \
  --font "jigmo=0=$HOME/projects/Philology/han2ids/cache/fonts/jigmo/Jigmo.ttf" \
  --font "jigmo=0=$HOME/projects/Philology/han2ids/cache/fonts/jigmo/Jigmo2.ttf" \
  --font "jigmo=0=$HOME/projects/Philology/han2ids/cache/fonts/jigmo/Jigmo3.ttf" \
  --audit-legacy-crop --limit 3
```

The output directory must not already exist. Omit `--limit` for all rows; use `--size` and `--padding` to change the default 224 and 12 pixels. `inputs.jsonl` contains opaque sample IDs, image paths and SHA-256 hashes of PNG bytes. `references.jsonl` is separate and contains the complete source row, original labels, face identity and unreviewed status. `fonts.json` records file hashes, names, face indices, source manifest hash and rendering library versions. IDs bind the source manifest hash, zero-based row, chosen face hash/index and render settings; they do not attest to label accuracy. Source paths are recorded as supplied after resolution; avoid sharing them if sensitive.

`--original-array` memory-maps the original array, checks its row count and records the SHA-256 of each selected row's C-order uint8 pixels in the references. These hashes identify row data, not the entire NPY file or proof that the array was produced from the supplied manifest. Array order must be verified independently.

Rendering uses an explicitly selected face without fallback, measures the actual foreground on a large white canvas, centers a square crop with padding, checks all foreground lies inside it, and scales uniformly. Canvas-boundary contact and out-of-range font metrics are rejected. This normalizes visual ink size and position, changing the model's input distribution. A cmap entry and visible ink establish coverage, not the identity or correctness of a glyph or IDS label. Fonts can differ in glyph conventions; all references require human adjudication. Pin the recorded Python, Pillow, FreeType, fontTools and NumPy versions when comparing output hashes across machines.

`--audit-legacy-crop` writes `legacy-audit.jsonl`, one record per sample. It reproduces the v0.3 draw at font size 224 and measures nonwhite pixels outside its `(60, 0, 260, 200)` crop against a larger canvas. Side counts partition loss into top, bottom, left and right; `outside_legacy_canvas_pixels` separately counts ink beyond the original 320×320 canvas and can overlap the side counts. This is a re-render with the supplied fonts and current FreeType/layout engine, not a measurement of the original NPY image. The crop audit rejects ink touching the outer audit canvas; its successful records mark that boundary as clear.
