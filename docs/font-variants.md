# Regional glyph variants

An IDS describes the tree of the printed glyph, not an abstract code point. The same character can
print with different components in Japanese, Taiwanese and mainland fonts, and an IVD may be encoded
as a variation sequence rather than a separate character. A single character-level gold label cannot
be right for every face.

## The preview font

The small character to the left of `U+…` in the galleries is the card's Unicode preview, not the
image. Its CSS is `font-family: "IDS Noto", "IDS Jigmo", serif`; `IDS Noto` is the bundled
`fonts/NotoSerifCJKjp-VF-2.003.ttf` (Noto Serif CJK JP variable 2.003), with Jigmo/Jigmo2 as fallback
when Noto lacks the character. The image on the left is the actual test glyph, from Noto, IPAmj or
Jigmo. A disagreement between the preview and the model image is therefore often a disagreement
between Noto JP and the source face.

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
| U+4885 | IPAmj | 𦥑 against the preview's 臼 |
| U+4635 | IPAmj | 彔 against the preview's 录 |
| U+51D1 | Noto | 𡗗+夭 against the preview's 奏 |
| U+53A7 | IPAmj | 眞 against the preview's 真 |
| U+55AD | IPAmj | 彥 against the preview's 彦 |
| U+61F2 | Jigmo | expanded 徵 against the preview's 徵 |
| U+6011 | IPAmj/Jigmo | ⿻八𰀁 against the preview's 半 |
| U+631B | Noto | 亦 against the preview's 𰁜 |
| U+3AE6 | IPAmj | 攵 against the preview's 夂 |
| U+399C | Jigmo | 蒦 expanded as 卝+隻; the preview uses 蒦 |
| U+3B36 | IPAmj | 吿 against the preview's 告 |
| U+3EBF, U+41EB | IPAmj | 𦣝 against the preview's 𦣞 |
| U+4100, U+4101 | IPAmj | 示 against the preview's 礻 |
| U+425B | IPAmj | 奧 against the preview's 奥 |
| U+42ED, U+4300, U+4328, U+431E, U+4311 | IPAmj | 糸 against the preview's 糹 |
| U+34EC | IPAmj | 龹+刀 against the preview font's 券 |
| U+34DE | Jigmo | 丯 against the preview font's 丰 |
| U+3423 | Jigmo | 庫 against 广+車 |
| U+356F | all | 內 and 内 are regional forms |
| U+300C | — | no IDS row in the current test; the reference is unresolved |

These are not model misses: U+50C3 `⿰亻𤰈` and U+5AD3 `⿱⿱…` are the same trees as the fuller
spellings, U+306A9 `辱` is `⿸辰寸`, U+3423 `庫` is `⿸广車`, U+3793 `尼+日` is `尸+旨`, and U+37F5
`罡` is `罒+正`; U+3DBE `⿳覀一火` and `⿱覀灭` are the same. `src/han2ids/tree.py` normalises equal-axis operator nesting (`⿱⿱ABC` = `⿳ABC`,
`⿰⿰ABC` = `⿲ABC`), and `data/equivalence-overrides.tsv` records the reviewed rare cases.

## Printed forms and the unified reading

A reading names the form the image prints. Where the form is a registered variation sequence, the
component carries its selector; `han2ids.forms.unify` gives the unified reading, with every listed
form replaced by the component that stands for it. `src/han2ids/unified-forms.tsv` holds the forms and
`data/font-label-overrides.tsv` the label of each reviewed face.

䦳 (U+49B3) prints three forms of its inner component:

| face | middle of the component | label | unified |
| --- | --- | --- | --- |
| Noto Serif CJK JP | 良, with a slanted last stroke | `⿵門鄉` | `⿵門鄉` |
| IPAmj | 皀 (白 over 匕) | `⿵門鄕󠄂` | `⿵門鄉` |
| Jigmo | a dot, 日 and two level ticks | `⿵門鄕󠄁` | `⿵門鄉` |

`鄕󠄂` is U+9115 U+E0102 (Moji_Joho MJ026366, Hanyo-Denshi IP9115) and `鄕󠄁` is U+9115 U+E0101
(Moji_Joho MJ026367, Hanyo-Denshi JC9276), the Japanese source glyph whose middle BabelStone lists as
the unencoded component `{74}`. U+E0102 was chosen over U+E0105 by eye from IPAmj at 560 px; the two
are close and the choice is uncertain. The 50 dataset images whose label holds 鄉, 鄕, 鄊 or 郷 were
reviewed the same way on 2026-11-12: 響 prints 郷 in all three faces, 饗 the Japanese source form,
and 嚮 that form with a bar for the dot, which has no registered sequence and is labelled `〾⿱鄕󠄁向`.

## Consequence for training

The current checkpoints use one gold label per character. A font-aware model needs either:

1. a gold label per (character, font), using BabelStone's region tags; or
2. multiple candidates ranked by confidence, with a font profile choosing among them.

The second is already exposed by `han2ids --top-k`; see `docs/multiple-ids.md`.

Sources: BabelStone IDS <https://www.babelstone.co.uk/CJK/IDS.TXT>; Unicode IVD
<https://www.unicode.org/reports/tr37/> and its sequence list of 2022-09-13
<https://www.unicode.org/ivd/data/2022-09-13/IVD_Sequences.txt>; review notes of 2026-11-10.
