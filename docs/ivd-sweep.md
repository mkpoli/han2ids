# IVD sweep

Every registered ideographic variation sequence, drawn by the faces that carry it and read by v0.5.
The sweep has no reference sequences: it shows what the reader makes of each registered form, and
whether it tells a form from its base character.

## Run

```sh
uv run python scripts/fetch_fonts.py
curl -o cache/ivd/IVD_Sequences-2026-08-03.txt https://www.unicode.org/ivd/data/2026-08-03/IVD_Sequences.txt
uv run --extra train python scripts/ivd_sweep.py --sequences cache/ivd/IVD_Sequences-2026-08-03.txt \
  --face jigmo=0=cache/fonts/jigmo/Jigmo.ttf --face jigmo=0=cache/fonts/jigmo/Jigmo2.ttf \
  --face jigmo=0=cache/fonts/jigmo/Jigmo3.ttf --face ipamj=0=cache/fonts/ipamj/ipamjm.ttf \
  --face noto=0=/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc --output build/ivd/sweep.jsonl
uv run python scripts/ivd_page.py --sweep build/ivd/sweep.jsonl --output build/ivd/index.html \
  --font jigmo=../../cache/fonts/jigmo/Jigmo.ttf --font jigmo=../../cache/fonts/jigmo/Jigmo2.ttf \
  --font jigmo=../../cache/fonts/jigmo/Jigmo3.ttf --font ipamj=../../cache/fonts/ipamj/ipamjm.ttf \
  --font noto=file:///usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc
```

`build/ivd/index.html` opens from disk: type characters to see each variant, drawn as text with its
selector in the face the sweep used, grouped by reading.

## Result

The list of 2026-08-03 registers 39,509 sequences over 29,642 pairs of base and selector. Jigmo draws
29,635 of the pairs, IPAmj Mincho 11,385 and Noto Serif CJK JP 14,682, for 55,702 readings of 15,302
characters. The readings are in [`ivd-sweep/sweep-v0.5.jsonl.gz`](ivd-sweep/sweep-v0.5.jsonl.gz).

| Face | Pairs drawn | Read as the base character in that face |
| --- | ---: | ---: |
| Jigmo | 29,635 | 91.8% |
| IPAmj Mincho | 11,385 | 89.1% |
| Noto Serif CJK JP | 14,682 | 98.5% |
| all | 55,702 | 93.0% |

1,906 characters get more than one reading across their variants; 𠔥 gets 13, 龜 12, 龍 11 and 器 10.
Many sequences share a glyph with their base character, so a high share read as the base is expected.

| | Drawn | Readings | Most common |
| --- | ---: | ---: | --- |
| 邊 U+908A | 40 | 5 | `⿺辶臱` 28, `⿺辶⿳自穴方` 6, `⿺辶⿳白㓁方` 2, `⿺辶⿳白冖方` 2, `⿺辶⿳白穴方` 2 |
| 邉 U+9089 | 63 | 8 | `⿺辶⿳自穴口` 27, `⿺辶⿳自㓁口` 11, `⿺辶⿳白㓁口` 7, `⿺辶⿱自容` 6, `⿺辶𦤝` 4 |

The reader separates 自 from 白 and 穴 from 㓁 and 冖 in the middle of these forms. Whether each
separation is right has not been checked against the images by a person. A reading different from
the base character is not thereby correct, and a shared reading can hide a difference the vocabulary
has no component for.

Sources: Unicode [Ideographic Variation Database](https://www.unicode.org/ivd/), `IVD_Sequences.txt`
of 2026-08-03, SHA-256 `2b466659c2bfde1c52e60bd9fc883ab14dfa5c583df024b80352420265d2cd87`;
[UTS #37](https://www.unicode.org/reports/tr37/). Faces as in `docs/fonts.md`.
