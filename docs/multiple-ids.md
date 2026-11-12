# Multiple IDS candidates

`han2ids` decodes with a grammar-constrained beam. Each beam keeps the IDS operand stack, so every
candidate is syntactically valid.

```console
$ han2ids samples/疑-ipamj.png --top-k 3
samples/疑-ipamj.png  1  ⿰𠤕⿱龴疋  ⿰𠤕⿱龴疋  0.843
samples/疑-ipamj.png  2  ⿰⿱匕矢⿱龴疋  ⿰⿱匕矢⿱龴疋  0.780
samples/疑-ipamj.png  3  ⿱⿰匕龴疋  ⿱⿰匕龴疋  0.508
```

The score is the geometric mean token probability. Candidates are deduplicated after decoding.
`--json` returns the same list under `readings`. `--top-k 1` is the normal greedy path.

The beam is useful exactly where one glyph has several defensible descriptions: IVD forms, 糸/糹,
示/礻, 靑/青, and the J/T differences in `docs/font-variants.md`. The model sees only the image; it has
no font metadata, so it can rank the variant forms but cannot choose by the source face. A future
font profile can rerank the same candidates.

The decoder is in `src/han2ids/grammar.py` (`generate_beam`); the CLI path is
`src/han2ids/infer.py` (`read_topk`).
