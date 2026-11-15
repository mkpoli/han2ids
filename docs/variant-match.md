# Variant match

`han2ids --variants` names the registered form a glyph image draws: a variation sequence with its
IVD collection and identifier, a compatibility ideograph, or the character as a regional face draws
it. It answers `matched`, `ambiguous` or `none`. The reading itself is unchanged, and without the flag
nothing here is loaded.

## Run

```sh
uv sync --extra variants
uv run python scripts/fetch_fonts.py
curl --create-dirs -o cache/ivd/IVD_Sequences-2026-08-03.txt https://www.unicode.org/ivd/data/2026-08-03/IVD_Sequences.txt
curl --create-dirs -o cache/ucd/StandardizedVariants-17.0.0.txt https://www.unicode.org/Public/17.0.0/ucd/StandardizedVariants.txt
uv run han2ids --variants samples/葛.png
uv run han2ids --variants --char 葛 --json samples/葛.png
```

`samples/葛.png` is U+845B U+E0100 drawn by Noto Serif CJK JP Bold, a weight outside the candidates:

```console
$ uv run han2ids --variants samples/葛.png
samples/葛.png	⿱艹曷	⿱艹曷	0.948	ambiguous	U+845B U+E0100 (Adobe-Japan1 CID+1481); U+845B U+E0102 (Hanyo-Denshi JA1975, Moji_Joho MJ022335); U+845B U+E0107 (Hanyo-Denshi KS352870, Moji_Joho MJ022337)
```

Three sequences answer. U+E0100 is the Adobe-Japan1 sequence the image was drawn from; the other
two are Hanyo-Denshi and Moji_Joho sequences that IPAmj Mincho and Jigmo draw like it, and the
image does not choose among them.

Without `--char` the candidates are the forms of every character whose BabelStone sequence equals
the reading. Of the 55,702 readings of the [IVD sweep](ivd-sweep.md), 51,021 (91.6%) name the
character that was drawn, 3,918 (7.0%) name no character and 763 (1.4%) name only another one. A
reading that names no character answers `none` with the reason `no-character`; `--char` gives the
character instead.

## Candidates

Each face of each font file gives, for a character:

- the character alone;
- every variation sequence the face's cmap carries for it, with its registrations from
  `IVD_Sequences.txt`;
- every standardized variation sequence `StandardizedVariants.txt` lists for it, and every
  compatibility ideograph whose canonical decomposition is the character.

The fonts are Jigmo, IPAmj Mincho and the five faces of Noto Serif CJK Regular. A face's region
(JP, KR, SC, TC, HK) is read from its name table; the installed collection holds them in that order
at indices 0 to 4. A font file that is absent is left out. The candidates are drawn with the sweep's
renderer: RAQM layout, the ink fitted with a 12 px margin.

Candidates that one font file draws with the same pixels are one shape. A shape names its sequences
and compatibility ideographs. A shape without any names the regional design when a regional face
draws it, and otherwise names nothing: it is a font's own drawing of the character.

## Verdict

The image, framed like the candidates, and each shape pass through the checkpoint's encoder. The
score is the cosine of the two means of the patch tokens.

| Verdict | Reason | When |
| --- | --- | --- |
| `none` | `no-close-form` | the best score is under 0.93 |
| `none` | `no-character` | the reading names no character |
| `none` | `no-candidate` | no font draws the character, or the image has no ink |
| `matched` | | the shapes that answer name one form, or none: the character alone |
| `ambiguous` | `identical-shape` | they name several forms and one font draws all of them with the same pixels |
| `ambiguous` | `close-shapes` | they name several forms otherwise |

The shapes that answer are those within 0.03 of the best score, or within twice the best score's
distance from 1 when that is less. The second bound holds an image that is almost exactly one
font's drawing to that drawing.

## Output

With `--json` each image's object gains `variants`:

```json
{
  "image": "samples/葛.png", "ids": "⿱艹曷", "unified": "⿱艹曷", "confidence": 0.9482,
  "variant": "em", "valid": true,
  "variants": {
    "chars": ["葛"], "verdict": "ambiguous", "reason": "close-shapes",
    "labels": [
      {"kind": "ivs", "sequence": "U+845B U+E0100", "text": "葛󠄀", "registrations": [{"collection": "Adobe-Japan1", "identifier": "CID+1481"}]},
      {"kind": "ivs", "sequence": "U+845B U+E0102", "text": "葛󠄂", "registrations": [{"collection": "Hanyo-Denshi", "identifier": "JA1975"}, {"collection": "Moji_Joho", "identifier": "MJ022335"}]},
      {"kind": "ivs", "sequence": "U+845B U+E0107", "text": "葛󠄇", "registrations": [{"collection": "Hanyo-Denshi", "identifier": "KS352870"}, {"collection": "Moji_Joho", "identifier": "MJ022337"}]}
    ],
    "regions": [],
    "shapes": [
      {"score": 0.9686, "answer": true, "candidates": [
        {"kind": "ivs", "sequence": "U+845B U+E0100", "text": "葛󠄀", "registrations": [{"collection": "Adobe-Japan1", "identifier": "CID+1481"}], "font": "Noto Serif CJK JP", "face": "JP"}
      ]},
      {"score": 0.9573, "answer": true, "candidates": [
        {"kind": "ivs", "sequence": "U+845B U+E0100", "text": "葛󠄀", "registrations": [{"collection": "Adobe-Japan1", "identifier": "CID+1481"}], "font": "Jigmo Regular", "face": null}
      ]}
    ]
  }
}
```

`labels` holds the forms that answer, `regions` the regional faces whose own drawing of the
character is among the shapes that answer, and `shapes` every candidate shape in rank order with
its score. `shapes` is cut to its first two entries here. A label's `kind` is `ivs`, `standardized`,
`compatibility` or `plain`; a standardized sequence carries its ideograph in `compatibility`, and a
regional design carries `regions`. The tab-separated output adds the verdict and the labels.

From Python:

```python
from PIL import Image
from han2ids.infer import Han2IDS
from han2ids.variants import VariantMatcher

matcher = VariantMatcher(Han2IDS("models/han2ids-v0.5.pt"))
match = matcher.match(Image.open("samples/葛.png"), "葛")
match.verdict, match.reason, match.labels, match.regions
```

`matcher.match_reading(image, reading.ids)` takes the characters from a reading. The first match
of a character draws and embeds its candidates, 22 shapes for 葛; later matches of that character
embed only the image.

## Measurements

```sh
uv run --extra variants python scripts/variant_eval.py --output build/variants --device cpu --threads 4
uv run --extra variants python scripts/variant_eval.py --rows docs/variant-match/rows-v0.5.jsonl.gz
```

The sample is 1,500 characters that have a sequence two font families both draw, taken in a
seed-20261115 order from the 2026-08-03 list; they give 7,621 shapes. Characters at even positions
set the thresholds and the tables report the odd positions. Every query and every candidate's score
is in [`variant-match/rows-v0.5.jsonl.gz`](variant-match/rows-v0.5.jsonl.gz). The run used the CPU.

### Comparison

A query is one family's drawing of a sequence; the candidates are the other family's shapes of that
character. The table counts the queries whose best-scoring candidate carries the query's sequence.

| Comparison | Best candidate right, 2,667 queries |
| --- | ---: |
| Encoder, cosine of mean patch tokens | 2,505 (93.9%) |
| Mean nearest-ink distance at 96 px, both directions | 2,074 (77.8%) |
| Overlap over union of binarised ink at 64 px | 1,921 (72.0%) |

The encoder was chosen on this difference. A pilot on 1,600 other queries of the same kind, whose
script was not kept, compared its outputs: the mean of the final patch tokens gave 90.7%, the mean
after the ninth block 91.6%, the final tokens pooled to a 7 by 7 grid 91.3% and the class token
82.7%. The first three are within sampling error of each other, and the final tokens are what the
reader already computes.

### Across fonts

| | Queries | One form, right | Several forms, right one listed | One form, wrong | Several forms, right one missing | None |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 2667 | 1247 (46.8%) | 1390 (52.1%), 2.5 listed | 1 (0.0%) | 1 (0.0%) | 28 (1.0%) |
| Adobe-Japan1 | 1530 | 836 (54.6%) | 683 (44.6%), 2.5 listed | 1 (0.1%) | 1 (0.1%) | 9 (0.6%) |
| Hanyo-Denshi | 990 | 378 (38.2%) | 602 (60.8%), 2.5 listed | 0 (0.0%) | 0 (0.0%) | 10 (1.0%) |
| KRName | 4 | 0 (0.0%) | 4 (100.0%), 3.0 listed | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| Moji_Joho | 1137 | 411 (36.1%) | 707 (62.2%), 2.6 listed | 0 (0.0%) | 0 (0.0%) | 19 (1.7%) |
| Jigmo to NotoSerifCJK-Regular | 765 | 372 (48.6%) | 387 (50.6%), 2.3 listed | 1 (0.1%) | 1 (0.1%) | 4 (0.5%) |
| Jigmo to ipamjm | 568 | 274 (48.2%) | 284 (50.0%), 2.2 listed | 0 (0.0%) | 0 (0.0%) | 10 (1.8%) |
| NotoSerifCJK-Regular to Jigmo | 765 | 464 (60.7%) | 296 (38.7%), 2.7 listed | 0 (0.0%) | 0 (0.0%) | 5 (0.7%) |
| ipamjm to Jigmo | 569 | 137 (24.1%) | 423 (74.3%), 2.8 listed | 0 (0.0%) | 0 (0.0%) | 9 (1.6%) |

"One form, right" is `matched` with the query's sequence; "several forms" is `ambiguous`. A wrong
single answer is the outcome the thresholds were set to avoid: 1 of 2,667 here. The even half gave
these rates, with the ratio at 2:

| Floor | Margin | One form, right | Several, right one listed | One form, wrong | Several, right one missing | None | Random other character | Highest-scoring other character | Other forms only |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.90 | 0.03 | 48.2% | 51.5% | 0.1% | 0.0% | 0.1% | 0.0% | 3.1% | 69.2% |
| 0.92 | 0.03 | 48.1% | 51.3% | 0.1% | 0.0% | 0.5% | 0.0% | 0.7% | 56.9% |
| 0.93 | 0.00 | 72.8% | 20.0% | 5.4% | 0.8% | 1.0% | 0.0% | 0.3% | 52.2% |
| 0.93 | 0.01 | 61.9% | 35.8% | 1.0% | 0.2% | 1.0% | 0.0% | 0.3% | 52.2% |
| 0.93 | 0.02 | 52.8% | 45.7% | 0.3% | 0.1% | 1.0% | 0.0% | 0.3% | 52.2% |
| 0.93 | 0.03 | 47.8% | 51.0% | 0.1% | 0.0% | 1.0% | 0.0% | 0.3% | 52.2% |
| 0.93 | 0.05 | 43.2% | 55.8% | 0.0% | 0.0% | 1.0% | 0.0% | 0.3% | 52.2% |
| 0.94 | 0.03 | 47.2% | 50.2% | 0.1% | 0.0% | 2.4% | 0.0% | 0.1% | 45.3% |
| 0.95 | 0.03 | 45.5% | 48.2% | 0.1% | 0.0% | 6.1% | 0.0% | 0.0% | 36.6% |

The last three columns are the controls below at the same thresholds. A margin of 0.03 is the
smallest that leaves the wrong single answers at 0.1%. A floor of 0.93 refuses 1.0% of the right
forms and lets through 0.3% of the highest-scoring other characters; 0.95 would refuse 6.1%.

With more fonts among the candidates:

| | Queries | One form, right | Several forms, right one listed | One form, wrong | Several forms, right one missing | None |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| every other family at once | 2435 | 922 (37.9%) | 1470 (60.4%), 3.0 listed | 22 (0.9%) | 5 (0.2%) | 16 (0.7%) |
| every family, the query drawn at 96 px | 2435 | 1499 (61.6%) | 936 (38.4%), 2.4 listed | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| the same without the ratio | 2435 | 960 (39.4%) | 1475 (60.6%), 2.7 listed | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |

Against every other family at once, 22 single answers (0.9%) name another sequence than the
query's. With several collections among the candidates, one collection's sequence for a like drawing
can stand alone above the margin; nobody has checked whether these 22 are one design under two
names. The last two rows draw the query again at 96 px in its own font and match it against every
family, that font included: the ratio turns 539 answers from several forms to one and none of them
wrong. Collections other than these four are drawn by Jigmo alone, so they have no second font to be
tested against.

### Controls

| Query against | Queries | Matched or ambiguous |
| --- | ---: | ---: |
| a random other character | 2667 | 0 (0.0%) |
| the highest-scoring other character of the sample | 2667 | 8 (0.3%) |
| the other forms of its character | 1400 | 783 (55.9%) |
| the other forms, the nearest scoring under 0.90 in the query's font | 220 | 1 (0.5%) |
| the other forms, the nearest scoring 0.90 to 0.95 in the query's font | 369 | 77 (20.9%) |
| the other forms, the nearest scoring 0.95 and over in the query's font | 811 | 705 (86.9%) |

The last four rows keep only the candidates of forms that the query's own font draws differently,
so no right answer is left, and group the queries by the score of the nearest such form inside the
query's font. When that form scores under 0.90 the query is refused. When it scores 0.95 or more,
which in the thirty pairs looked at is a difference of a stroke or a dot, the query is given the
candidates' names 86.9% of the time: such a form scores as high as another font's drawing of the
same form. Over all 1,400 queries 55.9% are answered. The encoder was trained to write an IDS, which
such a stroke does not change. Telling these forms apart needs a comparison trained on pairs of
registered forms, which [pair comparison](pair-comparison.md) measures; a higher floor refuses right
answers first.

### Regional designs

Of 3,000 characters taken in a seed-20261117 order from the 29,835 unified ideographs that all five
faces of Noto Serif CJK Regular map, 1,738 (57.9%) have one drawing in all five faces, 789 have two,
389 three, 80 four and 4 five. For the 1,738 no image can tell the regions apart.

| Query face | Queries | Exact regions | Right regions and more | Some right | Wrong | No regional face | None | Best regional candidate right |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Noto Serif CJK Bold | 610 | 227 (37.2%) | 373 (61.1%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 10 (1.6%) | 580 (95.1%) |
| Noto Sans CJK Regular | 606 | 79 (13.0%) | 215 (35.5%) | 3 (0.5%) | 0 (0.0%) | 0 (0.0%) | 309 (51.0%) | 480 (79.2%) |

The queries are the distinct drawings of 500 of the characters with more than one drawing, from the
five regional faces of Noto Serif CJK Bold and of Noto Sans CJK Regular, matched against the default
candidates; the table reports the 250 at odd positions. "Exact regions" answers with the faces that
share the query's drawing and no other; "right regions and more" adds faces whose drawing is within
the margin. The last column counts the queries whose best-scoring regional shape is the query's.
The sans design is outside the reader's scope and half of its queries are refused.

## Limits

- A verdict compares the image with the listed fonts' drawings. A typeface that draws a registered
  form differently enough scores under the floor and answers `none`.
- An image of a form no candidate carries is given a registered form's name when the two are
  close; see the controls.
- `ambiguous` with `close-shapes` does not say whether the listed sequences are one design
  registered in several collections or designs a stroke apart.
- Nobody has checked the verdicts against the images by eye beyond the examples here.

## Sources

- Unicode [Ideographic Variation Database](https://www.unicode.org/ivd/), `IVD_Sequences.txt` of
  2026-08-03, SHA-256 `2b466659c2bfde1c52e60bd9fc883ab14dfa5c583df024b80352420265d2cd87`;
  [UTS #37](https://www.unicode.org/reports/tr37/). Unicode License v3.
- Unicode Character Database 17.0.0,
  [`StandardizedVariants.txt`](https://www.unicode.org/Public/17.0.0/ucd/StandardizedVariants.txt)
  dated 2025-07-30, SHA-256 `f55100b2fb11d3d75a37b8c1ab752192dbd1c4b12328c5ec6b38e3807c0ca597`.
  Unicode License v3.
- Canonical decompositions of the compatibility ideographs from Python's `unicodedata`, Unicode
  16.0.0 under Python 3.14.
- Jigmo 2025-09-12, CC0 1.0: `Jigmo.ttf` SHA-256
  `c8f295b9bd8f9f117a76b3a454aaaa1bb5b4babc18e254978c6deb88464e40cf`, `Jigmo2.ttf`
  `5da3582efe77e22073b86b3b86b556d7111148a76b957cfb53318a91da2efff0`, `Jigmo3.ttf`
  `815b18c1c670103723fe743090559208fdea47dc587ecb057a5a4721ee8dfeff`.
- IPAmj Mincho Ver.006.01, IPA Font License v1.0: `ipamjm.ttf` SHA-256
  `a3e84f495f3c388db7a1473bf1985c1c076d0c814100f10a027ca6853eb1e8cb`.
- Noto Serif CJK 2.002, SIL OFL 1.1: `NotoSerifCJK-Regular.ttc` SHA-256
  `93069d8e9e45d515cc421c971a79e6a5777704b348e36a9ef86578bf58adef77`. The regional queries use
  `NotoSerifCJK-Bold.ttc` `9d3c0d769c703cfe41c49cbe2b14d4718e26545593dc247485486335b783fe94` and Noto Sans CJK 2.004 `NotoSansCJK-Regular.ttc`
  `b76b0433203017ca80401b2ee0dd69350349871c4b19d504c34dbdd80541690a`.
