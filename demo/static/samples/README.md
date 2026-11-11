# Samples

| File | Contents | Source |
| --- | --- | --- |
| `sample-yi.png` | 疑, 256 × 256 | Added with the demo page in commit `8868bbd`; its face is not recorded. |
| `sheet-grid.png` | 明 曼 / 川 二, 448 × 448 | `demo/make_samples.py`, IPAmj Mincho Ver.006.01. |
| `sheet-row.png` | 疑 明 謝 鬱, 864 × 240 | `demo/make_samples.py`, IPAmj Mincho Ver.006.01. |
| `glyph-chuan.png` | 川, 240 × 240 | `demo/make_samples.py`, IPAmj Mincho Ver.006.01. |

The sheets carry the four structures the cut has to survive: a left-right pair whose halves are
separate shapes (明), stacked tiers (曼), repeated separate strokes (川) and a short wide glyph
whose ink fills a tenth of its cell (二).

- Font: [IPAmj Mincho](https://moji.or.jp/mojikiban/font/) Ver.006.01, Information-technology
  Promotion Agency, Japan. Fetched and checksummed by `scripts/fetch_fonts.py`; the same face the
  reader is trained on.
- Licence: IPA Font License Agreement v1.0. It places no condition on printed matter or digital
  documents produced with the font, which is what these renders are.

```sh
uv run python demo/make_samples.py --font cache/fonts/ipamj/ipamjm.ttf
```
