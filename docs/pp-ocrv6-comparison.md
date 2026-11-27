# Comparison with `fang718/pp-ocrv6-hanzi-ids-ocr`

[`fang718/pp-ocrv6-hanzi-ids-ocr`](https://huggingface.co/fang718/pp-ocrv6-hanzi-ids-ocr) (Hugging Face Hub, commit `3c7509ea89e82c4085840f18a291082cee3d6e1e`, 2026-09-26) is an open-source PyTorch glyph-to-IDS model.

## Identity with GlyphStudio 0.1.0

Every model artifact in `fang718/pp-ocrv6-hanzi-ids-ocr` matches the IDS model benchmarked as `GlyphStudio 0.1.0` in [`benchmark/RESULTS.md`](../benchmark/RESULTS.md) byte for byte:

| File | SHA-256 (both repositories) |
| --- | --- |
| `model.pt` | `8eff12b078a4e8748d0d7d158b22e9df477d9f9a103ca38c35fd3de9ee30b460` |
| `ensemble_1.pt` | `21de62d85772220e8c31ee82fe5d1fa867864e75ac4c94ebdcf35242d59891ac` |
| `inference_config.json` | `1bb3196857102e4235f5267901ceb903580682807957f3fd8e5aa3fd45cc4dbb` |
| `vocab.json` | `7f0d2c4be3a852bfcfb3574af1c5a521a929d83fa7140e1ed1f1af61a7112bda` |
| `normalization.json` | `4a83fed8522a677fed0cc3f3aa2a732d5a57a2c49211d3e4a85c5ec4058aa2b0` |
| `component_output_policy.json` | `047e5f83a737309a68d702d1a2488c8a963d60733ec2f44cb58598029b557e21` |

Its bundled `hanzi_ids/` package keeps the same model definition and decoding logic with package-relative imports (`hanzi_ids/__init__.py`).

## System comparison

| Aspect | `han2ids` v0.5 | `fang718/pp-ocrv6-hanzi-ids-ocr` |
| --- | --- | --- |
| Target domain | Mincho / Song serif faces (Noto, IPAmj, Jigmo) | Clean dark-on-light computer-font rare and unencoded glyph bitmaps (e-books, dictionaries such as *Nihon Kokugo Daijiten*, unencoded oracle-bone *liding* transcriptions; trained on regional Song, Hei, Fangsong and Kai faces) |
| Encoder | `vit_small_patch16_224.augreg_in21k_ft_in1k` (ViT-S/16) | PPLCNetV4-Medium (fused CNN, 2D feature map + row/column embeddings) |
| Input | 224×224 grayscale (3ch), `[-1, 1]` | 128×128 grayscale (3ch), `[-1, 1]` |
| Decoder | 4-layer Transformer, `d_model=384`, 6 heads, FFN 1536, `max_len=48` | 4-layer Transformer, `d_model=256`, 8 heads, FFN 1024, `max_len=96` |
| Parameters & disk size | 35.2M (1 checkpoint: 140.9 MB fp32; 40.2 MB int8 ONNX) | 19.7M × 2 ensemble = 39.3M (157.5 MB fp32) |
| Vocabulary | 10,428 tokens (10,406 atomic component/form tokens, BabelStone IDS) | 3,459 tokens (`yi-bai/ids` `ids_lv1.txt`, zi.tools dialect) |
| Training objective | Cross-entropy with label smoothing (0.05) | Marginal log-sum-exp over accepted alternative decompositions |
| Sampling weights | Composed glyphs (20% batch), ink-fitted (50%), form repeat 20× | `extended_boost=4.0`, `long_boost=2.0`, `synthetic_weight=0.15`, `scale_jitter=0.08–0.12` |
| Decoding (shipped) | Operand-stack greedy (CLI default) or beam-5 | Cached-encoder 2-model probability-averaged beam-5 (widens to beam-12 if `< 5` distinct outputs) + canonical contraction and path merging |
| Single-component glyphs | Forces an operator at step 0 (over-decomposes `一`, `木`) | Over-decomposes `一`, `木` in practice (model card `Limitations`) |

## Accuracy comparison

Published benchmark numbers come from [`benchmark/RESULTS.md`](../benchmark/RESULTS.md) and its score bundles (`benchmark/results/*/scores/`). Prototype rows evaluate the same `han2ids-v0.5.pt` checkpoint with cached-encoder batched beam-5, same-axis tree probability merging, and 2-view (`em` + `fit 0.08`) probability ensembling.

### Clean track (8,730 images, 4,752 held-out characters)

| System | Image exact | Char exact | Char same-axis | Char expanded (CHISE) | Top-5 same-axis (img / chr) | Invalid / unsupported |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `han2ids` v0.5 (greedy-batched) | 86.01% | 83.77% | 84.07% | 85.98–91.95% | — | 0 / 0 |
| `han2ids` v0.5 (beam-5 prototype) | 86.36% | 84.05% | 84.34% | — | 92.26% / 90.77% | 0 / 0 |
| `han2ids` v0.5 (beam-5 + tree merge) | 86.39% | 84.08% | 84.38% | — | 92.26% / 90.77% | 0 / 0 |
| `han2ids` v0.5 (beam-5 + 2-view TTA) | 86.45% | 84.12% | 84.39% | — | 92.39% / 90.95% | 0 / 0 |
| `fang718` (2-model ensemble beam-5) | 64.51% | 61.92% | 62.53% | 81.64–92.53% | 67.88% / 65.41% | 9 / 47 |

### Matched style track (1,346 images, 673 characters)

| System | Overall exact | Shippori ExtraBold | Noto Sans CJK JP | Top-5 same-axis |
| --- | ---: | ---: | ---: | ---: |
| `han2ids` v0.5 (greedy-batched) | 90.64% | 91.83% | 89.45% | — |
| `han2ids` v0.5 (beam-5 prototype) | 92.05% | 93.02% | 91.08% | 96.21% |
| `han2ids` v0.5 (beam-5 + 2-view TTA) | 92.57% | 93.61% | 91.53% | 96.58% |
| `fang718` (2-model ensemble beam-5) | 70.73% (86.63–94.50% exp.) | 71.17% (86.92–94.80% exp.) | 70.28% (86.33–94.21% exp.) | 73.03% (89.08–98.51% exp.) |

### Head-to-head error dissection (clean track, CHISE selective expansion)

Comparing `clean-han-v05` against `clean-glyphstudio` across all 8,730 clean images:

- Both match (lower bound): **6,758**
- Indeterminate or tie: **1,046**
- Neither matches (upper bound): **250**
- `han2ids` v0.5 matches (lower) while `fang718` misses (upper): **335** (`noto`: 52, `ipamj`: 96, `jigmo`: 187)
- `fang718` matches (lower) while `han2ids` v0.5 misses (upper): **341** (`noto`: 23, `ipamj`: 108, `jigmo`: 210)

Two systematic patterns account for most of `fang718`'s 341 wins:

1. **Rare and unseen components (144 / 341 = 42.2% with `< 5` training occurrences in `han2ids`, including 116 unseen).** `han2ids` includes 10,406 atomic component/form tokens (10,428 total vocabulary entries); when a glyph holds a rare component such as `㧜` in `箍` (`⿱𥫗㧜`) or `𣐝` in `篐` (`⿱𥫗𣐝`), `han2ids` substitutes a visually similar common character (`捕`, `樞`). `fang718`'s 3,459-token vocabulary decomposes those parts into common subcomponents (`⿱𥫗⿰扌匝`, `⿱𥫗⿰木匝`).
2. **Long sequences (length ≥ 5: `fang718` leads 140 to 90).** `fang718` trains with `long_boost=2.0`, `extended_boost=4.0`, and `max_len=96`, and enforces a remaining-token budget mask at decode time. On dense glyphs such as `𰻞`, `fang718` outputs `⿺辶⿳穴⿲月⿱𮘎⿰長⿰馬長刂心`, while `han2ids` without a remaining-token budget mask hits `max_len=48` in an incomplete repetition loop.

## Inference latency

Measured on 16 tiled sample glyphs (`samples/*.png`, RTX 5070 Ti GPU and host CPU, PyTorch 2.15, FP32):

| Configuration | CPU (ms/img) | CUDA (ms/img) |
| --- | ---: | ---: |
| `han2ids` v0.5 (uncached) greedy, `batch=1`, `--no-tta` | 405.1 | 63.0 |
| `han2ids` v0.5 (uncached) greedy, `batch=1`, 4-view TTA | 1,659.6 | 249.7 |
| `han2ids` v0.5 (uncached) beam-5, `batch=1`, `--no-tta` | 2,188.9 | 227.8 |
| `han2ids` v0.5 (uncached) greedy, `batch=16` | 257.1 | 13.2 |
| `han2ids` v0.5 (cached encoder) greedy, `batch=1`, `--no-tta` | **115.9** | **35.8** |
| `han2ids` v0.5 (cached encoder) beam-5, `batch=1`, `--no-tta` | **149.5** | **51.6** |
| `han2ids` v0.5 (cached encoder) beam-5, `batch=1`, 2-view TTA | **331.4** | **83.6** |
| `han2ids` v0.5 (cached encoder) greedy, `batch=16` | **35.0** | **5.1** |
| `han2ids` v0.5 (cached encoder) beam-5, `batch=16`, `--no-tta` | **115.3** | **7.6** |
| `han2ids` v0.5 (cached encoder) beam-5, `batch=16`, 2-view TTA | **234.4** | **13.5** |
| `fang718` 2-model ensemble beam-5, `batch=1` | 330.1 | 144.7 |
| `fang718` 2-model ensemble beam-5, `batch=16` | 371.4 | 30.3 |
| `fang718` single model beam-5, `batch=16` | 139.6 | 5.0 |

Caching the encoder output across autoregressive steps cuts `han2ids` single-image beam-5 latency by 14.6× on CPU and 4.4× on CUDA. At `batch=16`, cached single-view (`--no-tta`) beam-5 runs 3.2× faster on CPU and 4.0× faster on CUDA than `fang718`'s 2-model ensemble; 2-view TTA beam-5 runs 1.6× faster on CPU and 2.2× faster on CUDA.

## Candidate training directions for v0.6

1. **Compact component vocabulary or deep-decomposition fallback:** expand components occurring fewer than five times in training into their recursive IDS so rare components decompose into seen subparts.
2. **Marginal log-sum-exp loss over valid decompositions:** train over all accepted decompositions per glyph (shallow and deep, associative groupings such as `⿰⿰ABC` and `⿲ABC`) by summing sequence probability mass.
3. **Rare and complex sequence weighting:** sample rare/extended characters and longer trees more heavily (`extended_boost`, `long_boost`) and raise `max_len` above 48.

## Sources

- `fang718`, [`pp-ocrv6-hanzi-ids-ocr`](https://huggingface.co/fang718/pp-ocrv6-hanzi-ids-ocr), Hugging Face Hub, commit `3c7509ea89e82c4085840f18a291082cee3d6e1e`, 2026-09-26 (model card `Limitations`, `hanzi_ids/__init__.py`, `hanzi_ids/backbone_torch.py`, `hanzi_ids/ids_model.py`, `hanzi_ids/beam_batch.py`, `hanzi_ids/canonical_output.py`, `hanzi_ids/render_utils.py`).
- `fang718` (方), personal communication relayed 2026-11-24 regarding target domain (clean dark-on-light computer-font bitmap glyphs from e-books, dictionaries such as *Nihon Kokugo Daijiten*, and unencoded oracle-bone *liding* transcriptions; trained across regional Song, Hei, Fangsong and Kai faces; secondary relay).
- Yi Bai, [`yi-bai/ids`](https://github.com/yi-bai/ids), `ids_lv1.txt` (LF-normalized SHA-256 `51f78d7d84f52fd73e5bc155c2239b737c58ce627d446894a809f1a36547ae18`, MIT License, bundled in `fang718/pp-ocrv6-hanzi-ids-ocr` at `data/ids_lv1.txt`).
- PaddlePaddle Authors, [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) `rec_lcnetv4.py` (Apache-2.0 License, PyTorch port bundled in `fang718/pp-ocrv6-hanzi-ids-ocr` at `hanzi_ids/backbone_torch.py`).
- Andrew West, [BabelStone IDS](https://www.babelstone.co.uk/CJK/IDS.TXT), 2025-06-27 edition.
- Local benchmark bundles in [`benchmark/RESULTS.md`](../benchmark/RESULTS.md).
