# Regional glyph variants

An IDS describes the tree of the printed glyph, not an abstract code point. The same character can
print with different components in Japanese, Taiwanese and mainland fonts, and an IVD may be encoded
as a variation sequence rather than a separate character. A single character-level gold label cannot
be right for every face.

Reviewed cases (BabelStone region tags and Unicode IVD):

| character | font | difference |
| --- | --- | --- |
| U+2172B | IPAmj | 丹 is IVD U+4E39 U+E0101; the v0.1 expansion and `⿰女⿱厶丹` describe the same tree |
| U+7E49 | Noto / IPAmj / Jigmo | 糸 in Japanese and Korean forms, 糹 in the Chinese form |
| U+260F4 | Jigmo | 糸, not 糹; v0.1's 糸 is the Japanese form |
| U+21B82 | IPAmj / Jigmo | 小/𡭔 and 白/日 are font design choices |
| U+2569C, U+256A8 | IPAmj / Jigmo | 示, 礻 and 𱍐 are regional forms |
| U+270E0 | IPAmj / Jigmo | 靑 in IPAmj, 青 in Jigmo |
| U+2DD65 | Jigmo | BabelStone gives `⿸𦫺用` for T and `⿱艹⿸厂用` for J; Jigmo prints the J form |
| U+34EC | IPAmj | 龹+刀 against the preview font's 券 |
| U+34DE | Jigmo | 丯 against the preview font's 丰 |
| U+3423 | Jigmo | 庫 against 广+車 |
| U+356F | all | 內 and 内 are regional forms |
| U+300C | — | no IDS row in the current test; the reference is unresolved |

These are not model misses: U+50C3 `⿰亻𤰈` and U+5AD3 `⿱⿱…` are the same trees as the fuller
spellings, U+306A9 `辱` is `⿸辰寸`, U+3423 `庫` is `⿸广車`, U+3793 `尼+日` is `尸+旨`, and U+37F5
`罡` is `罒+正`. `src/han2ids/tree.py` normalises equal-axis operator nesting (`⿱⿱ABC` = `⿳ABC`,
`⿰⿰ABC` = `⿲ABC`), and `data/equivalence-overrides.tsv` records the reviewed rare cases.

## Consequence for training

The current checkpoints use one gold label per character. A font-aware model needs either:

1. a gold label per (character, font), using BabelStone's region tags; or
2. multiple candidates ranked by confidence, with a font profile choosing among them.

The second is already exposed by `han2ids --top-k`; see `docs/multiple-ids.md`.

Sources: BabelStone IDS <https://www.babelstone.co.uk/CJK/IDS.TXT>; Unicode IVD
<https://www.unicode.org/reports/tr37/>; review notes of 2026-11-10.
