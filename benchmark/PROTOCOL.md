# IDS benchmark protocol

## Scope and tracks

This benchmark compares ranked IDS predictions for the same glyph images. Prepared references are **unreviewed**: do not interpret agreement with them as reviewed glyph accuracy. A cmap entry and visible ink establish coverage, not glyph identity or label correctness. Unknown, unsupported or unparseable material is not successfully adjudicated, even when an exact string comparison happens to match it. The source IDS may describe regional glyphs differently; see Andrew West's [BabelStone IDS source and caveat](https://www.babelstone.co.uk/CJK/IDS.TXT).

- **Original pixels:** `benchmark.legacy dataset` exports a supplied uint8 N×H×W array losslessly, paired by row with its manifest. The manifest and array must have the same length and unique `(char, font)` keys. The original font files and row correspondence are not independently established by the export.
- **Clean render:** `benchmark.generate` re-renders each manifest row using the first explicitly mapped face in that family's cmap priority order. It renders visible ink on an oversized canvas, checks cropping and boundaries, centers a padded square and resizes uniformly. Defaults are 224 pixels with a requested 12-pixel margin before resampling; antialiasing can reduce the final white margin. Missing coverage, blank ink or unresolved clipping aborts publication. This changes the input distribution; it does not validate the labels. The optional legacy-crop audit measures a re-render with the supplied fonts and current software, not the historical array.
- **Paired style:** `benchmark.style_manifest` retains characters present in every required source family and in the cmap of every target face, then copies the single consistent source IDS to each target. It rejects duplicate `(char, font)` pairs and conflicting source labels. Target faces can have different glyph conventions; copied references remain unreviewed. Target cmap coverage establishes neither identity nor model exposure.

Sample IDs and PNG hashes bind inputs to preparation metadata. References, source rows, face hashes and review status are stored separately. Font and software provenance is recorded; paths in metadata may contain local information. `benchmark.review` prepares a model-identity-blind packet with source labels visible to the reviewer; this is label-assisted review. Review each image and its acceptable IDS alternatives before making glyph-accuracy claims. `reviewed_references` is accepted only on a row marked `reviewed` and must contain distinct, nonempty strings; the preferred `ids` remains part of the reference set.

For the existing v0.3 test split, the repository's [split audit](../docs/leak.md) reports that v0.1 training included many test characters; v0.1 is not a character-held-out comparator on that split. The [v0.3 training script](../scripts/train_fonts_v3.py) splits by character and trains on Noto, IPAmj and Jigmo faces; [v0.4 training](../scripts/train_fonts_v4.py) continues v0.3 using the same cache's training rows. These faces are therefore not held out as font families for v0.4. The v0.3 script also builds its vocabulary from all records, including test labels. For any other model or style face, training and pretraining exposure remain unknown unless independently documented; a new render alone cannot establish a held-out model or font.

## Input isolation and runs

The inference runner reads `inputs.jsonl` and its images, but no reference file. Input rows contain exactly `sample_id`, a relative raster image path and the image SHA-256. It resolves paths within the dataset, checks and decodes the same hashed bytes, and passes image objects to the adapter. References are read later by the scorer. This is a runner-level separation, not a sandbox against an untrusted adapter or model with filesystem access.

The runner records checkpoint and adapter hashes, settings, software, requested and actual device, warnings, failures and ranked candidates. A failed batch is retried per image; failures remain explicit. Rank 1 is the top prediction; top-five measures use at most the first five in adapter order. Han2IDS greedy, beam5 and batched greedy are different configurations; batched greedy requires `--no-tta`, and its confidence scores are not comparable with single-image confidences. The GlyphStudio adapter uses its shipped ensemble/beam configuration. Use trusted checkpoints. The runner records no timings: **speed is not measured**.

## Parser and normalization

The evaluator accepts one prefix IDS tree, including a single leaf. It implements all U+2FF0–U+2FFF operators with their arities, binary subtraction `㇯`, and unary variation indicator `〾`. Leaves are assigned characters in its explicit CJK ideograph, compatibility ideograph, radical and stroke ranges, plus U+3007, with at most one variation selector. Its assignment check uses a frozen Unicode 17 assignment table; coverage is bounded by the implemented ranges. See [Unicode 17, chapter 18](https://www.unicode.org/versions/Unicode17.0.0/core-spec/chapter-18/).

Input is limited to 512 code points and depth 64. Missing operands, trailing text, whitespace, stray selectors and unassigned components are invalid. Assigned letters and symbols outside the supported component repertoire, private-use characters, placeholders and extended notation are unsupported; this is not a general CHISE or BabelStone parser. Variation sequences remain distinct; no Unicode or variant folding is applied.

For structural comparisons, nested horizontal `⿰`/`⿲` nodes flatten to ordered `H` children, and nested vertical `⿱`/`⿳` nodes flatten to ordered `V` children. Other operators and child order remain distinct. The default evaluator does not expand components or infer aliases. For example, `⿰⿰木日月` and `⿲木日月` match structurally; their raw strings differ.

## Metrics and denominators

The scorer joins inputs, references and each run by unique sample ID and requires identical ID sets and a matching input-manifest hash. For each image, let the preferred reference be `ids` and the reference set include any explicitly reviewed alternatives. The scorer reports:

| Metric | Per-image definition |
| --- | --- |
| `raw_exact`, `recall_at_5` | Rank 1 equals the preferred string; or the preferred string occurs in ranks 1–5. |
| `parseable_exact`, `parseable_recall_at_5` | The same comparisons, restricted to images whose preferred reference parses successfully. |
| `reference_set_exact`, `reference_set_recall_at_5` | Rank 1, or any of ranks 1–5, equals a string in the reference set. These raw comparisons include unparseable strings. |
| `structural_match`, `structural_recall_at_5` | Normalized tree equality with any valid reference, at rank 1 or within ranks 1–5. |
| `family_match`, `family_recall_at_5` | Normalized tree equality allowing the selected policy's direct, position-specific leaf substitutions, at rank 1 or within ranks 1–5. Disabled without a policy. |
| `skeleton_accuracy` | Rank-1 normalized trees have identical ordered operators and tree shape after leaf labels are erased, against any valid reference. |
| `component_precision`, `component_recall`, `component_f1` | For rank 1, let overlap be the sum of minimum multiplicities of each leaf in prediction and reference. Precision is overlap / predicted leaf count; recall is overlap / reference leaf count; F1 is their harmonic mean, or zero if both sum to zero. Select the valid reference with highest F1, first on ties, and use all three values from it. |
| `tree_edit_similarity` | Maximum over valid references of `1 − distance / (prediction nodes + reference nodes)` on normalized ordered trees. Insert/delete cost 1, substitution cost 2; deletion promotes children. Each tree is capped at 64 nodes. |

Raw metrics use **all images**, including failures and unparseable references; a missing prediction is a miss. Other metrics use images with at least one valid reference; failed or invalid/unsupported predictions count as zero. Tree-edit uses the subset where every valid reference is within 64 nodes; an oversized prediction scores zero there. Invalid references are excluded from structural calculations and reported by status. Family scores have zero denominator when disabled. Top-five structural/family scores inspect each available candidate separately.

For every metric, `image_macro` is the mean over eligible images and `image_denominator` is their count. `character_macro` first averages eligible images within each character, then averages those character means; `character_denominator` counts characters with at least one eligible image. Per-font summaries apply the same rules within each font. Reports include sample and character counts, review proportions, reference and prediction statuses, candidate counts and tree-edit statuses; report denominators and coverage alongside every score.

Paired differences are first run minus second run. The scorer resamples characters with replacement, retaining every paired image in each sampled character cluster and using the same draw for both runs. Image-weighted and character-weighted differences have separate 95% percentile intervals, with linear interpolation at the 2.5th and 97.5th percentiles. Replicates without eligible samples are omitted and counted; eligible sets must agree between runs. Defaults are 2,000 draws and seed 0. These intervals quantify sampling variation under this cluster bootstrap, not label or exposure uncertainty.

## Provisional family policy

The optional [component-families-v1.json](component-families-v1.json) accepts six named pairs only as child 0 of a normalized horizontal node, at any depth. It applies direct substitutions without transitive closure, preserves the tree and does not change strict metrics. The policy is editorial and has no independent glyph-level review. Its source notes cite [Unicode 17 radical-stroke discussion](https://www.unicode.org/versions/Unicode17.0.0/core-spec/chapter-18/#G37685) and [UAX #38 `kRSUnicode`](https://www.unicode.org/reports/tr38/#kRSUnicode); radical classification and glyph variation do not prescribe these IDS equivalences or prove visual interchangeability. The scorer records the policy document and SHA-256.

## Optional expansion sensitivity

`benchmark.score_expansion` is a separate, experimental decomposition-allowance analysis, not image-gold correctness. Family aliases are disabled unless a policy is supplied. Supply one or more local CHISE-style TSV sources, each with a SHA-256, provenance and license in a source-spec JSON; no source is bundled. The [CHISE IDS package README and license](https://gitlab.chise.org/CHISE/ids/-/raw/main/README.md) specifies GPL-2.0-or-later for the package; verify the terms of each supplied source and redistribution. The loader expects Unicode key, matching character and one or more tab-separated definitions, with `;;` comments. CHISE entity references and extended annotations are not resolved.

A component is expandable only when all supplied definitions are one identical parseable operator-bearing IDS. Duplicate identical definitions are allowed; missing or atomic definitions remain leaves, while malformed, conflicting or unparseable definitions make an encountered component uncertain. Both trees expand symmetrically and then undergo same-axis normalization; traces record substitutions. Root leaves are never expanded. A target-character leaf below the root, including a variation sequence, is blocked whether originally present or introduced by a definition. Active-path cycles, parse failures, uncertainty and depth/node limits produce indeterminate comparisons, not matches. The scoring defaults are depth 64 and 1,024 nodes per expanded tree; lookup does not fold variation sequences or resolve regional variants.

The analysis compares rank 1 against each reference. Any successful expansion match wins; otherwise any indeterminate comparison makes the outcome indeterminate. With no prediction it is a miss. `strict_hit` is raw reference-set equality or structural equality; `relaxed_hit` adds successful expansion matches. With a family policy, `family_only_hit` adds direct family substitutions and `combined_hit` accepts either allowance or both together. The corresponding upper bounds additionally count indeterminate expansions as hits. These are sensitivity bounds, not adjudicated accuracy. Strict hits remain hits even when expansion is indeterminate, including raw equality of unparseable strings.

Expansion summaries report image and character denominators and coverage. Raw, strict, added and relaxed bounds use all images; `structural_match` and `eligible_*` use the prediction-independent set with at least one parseable reference. `expansion_match` excludes indeterminate outcomes, so its coverage depends on predictions; no paired interval is calculated for it. With positive `--bootstrap-iterations`, paired intervals for the other metrics use the same character-cluster percentile method and fixed reference eligibility; their paired image and character denominators are reported.

`benchmark.score_selective` additionally searches selective non-root expansions and direct contextual aliases in either order. Each leaf can take one direct alias before expansion; no transitive alias closure is assumed. The search has a configurable state cap and returns indeterminate for unresolved branches or ambiguous alias history. Its lower score retains strict, family and exhaustive-expansion hits and adds witnessed selective matches; the upper score also counts indeterminate cases. Top-five recall evaluates the same ranked list. These bounds describe the specified search and rules, not all possible descriptions or human correctness. Paired intervals for the lower and upper scores do not cover reference or policy uncertainty.

Full selective outputs contain the transformation witnesses. `benchmark.summarize_selective` strips dictionary-derived traces for publication while retaining per-image scores, status, source hashes and aggregate intervals. The witnesses can be regenerated with the pinned external sources and the published predictions.

## Published bundles

Each bundle's `bundle.json` records stored and uncompressed SHA-256 hashes. Copy a bundle to a writable directory, decompress its `.json.gz` and `.jsonl.gz` files, then extract `dataset/images.tar.gz` inside `dataset/`. The candidate bundle shares image paths and hashes with the clean bundle. The legacy bundle omits original images. Run metadata is path-redacted; `bundle.json` retains the original and published metadata hashes. Bundles publish labels and predictions and are therefore not blind test sets.

## Commands

Run from the repository root in an environment with the project dependencies, Pillow, fontTools and NumPy (`uv sync --extra train --extra dev` installs the project extras). Replace every `$VARIABLE` with a local path or value. Output directories and score files must be new; inference outputs must be outside the dataset directory. Use the complete manifest for scoring: inference `--limit` creates an ID subset that the scorer rejects against a full dataset.

```sh
# Clean render: supply mappings for every source family, repeating in priority order.
python -m benchmark.generate --manifest "$TEST_MANIFEST" --out "$CLEAN_DATASET" \
  --font "noto=0=$NOTO_FONT" --font "ipamj=0=$IPAMJ_FONT" \
  --font "jigmo=0=$JIGMO_FONT" --font "jigmo=0=$JIGMO2_FONT" \
  --font "jigmo=0=$JIGMO3_FONT" --original-array "$TEST_ARRAY" --audit-legacy-crop

# Optional original-pixel track.
python -m benchmark.legacy dataset --manifest "$TEST_MANIFEST" --array "$TEST_ARRAY" --out "$ORIGINAL_DATASET"

# Paired style manifest and its renders; each target family has one explicit face.
python -m benchmark.style_manifest --manifest "$TEST_MANIFEST" --out "$STYLE_MANIFEST_DIR" \
  --require-original-font noto --require-original-font ipamj --require-original-font jigmo \
  --font-family "style-a=0=$STYLE_A_FONT" --font-family "style-b=0=$STYLE_B_FONT"
python -m benchmark.generate --manifest "$STYLE_MANIFEST_DIR/manifest.jsonl" --out "$STYLE_DATASET" \
  --font "style-a=0=$STYLE_A_FONT" --font "style-b=0=$STYLE_B_FONT"

# Clean-track settings: batched greedy em-box and the GlyphStudio IDS ensemble.
python -m benchmark.infer --dataset "$DATASET" --system han2ids --checkpoint "$TRUSTED_CHECKPOINT" \
  --output "$RUN_HAN" --device auto --decode greedy-batched --no-tta --batch-size 4
python -m benchmark.infer --dataset "$DATASET" --system glyphstudio --app "$GLYPHSTUDIO_ROOT" \
  --output "$RUN_GLYPH" --device auto --batch-size 2
# For the ranked-candidate sample, generate a separate han2ids run with --decode beam5 --no-tta.

# Prepare a model-identity-blind, source-label-assisted review packet.
python -m benchmark.review export --dataset "$DATASET" --out "$REVIEW_PACKET" --characters 100 --seed 0
# After a person reviews the packet, import it as a new scoring dataset.
python -m benchmark.review import --dataset "$DATASET" --packet "$REVIEW_PACKET" --out "$REVIEWED_DATASET"

# Strict scores plus optional provisional family sensitivity.
python -m benchmark.score --dataset "$DATASET" --run "$RUN_HAN" --run "$RUN_GLYPH" \
  --family-policy benchmark/component-families-v1.json --bootstrap-iterations 2000 --seed 0 \
  --output "$SCORES_JSON"

# Obtain the pinned external CHISE files, then create verified local source specs.
git clone https://github.com/chise/ids.git "$CHISE_DIR"
git -C "$CHISE_DIR" checkout --detach c3057f890b4d7a990628873f19274ec33b58a7aa
python -m benchmark.prepare_chise --source-dir "$CHISE_DIR" --output "$CHISE_SPECS"
specs=(); for spec in "$CHISE_SPECS"/*.json; do specs+=(--source-spec "$spec"); done

# Optional selective expansion sensitivity; run this block in Bash.
python -m benchmark.score_selective --dataset "$DATASET" --run "$RUN_HAN" --run "$RUN_GLYPH" \
  "${specs[@]}" --family-policy benchmark/component-families-v1.json \
  --max-states 256 --bootstrap-iterations 2000 --seed 0 --output "$EXPANSION_SCORES_JSON"
```

Omit `--original-array` and `--audit-legacy-crop` when unavailable, and omit `--family-policy` for strict-only scoring. Repeat `--source-spec` for additional sources. A source spec has the following form; its relative `path`, if used, is resolved from the spec file's directory. Replace the digest with the actual source file's SHA-256 and provenance with its pinned revision and origin.

```json
{"path": "CHISE_SOURCE_PATH", "sha256": "SOURCE_SHA256", "provenance": "SOURCE_URL_AND_PINNED_REVISION", "license": "SOURCE_LICENSE"}
```
