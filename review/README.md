# Review desk

A local page for reviewing what han2ids reads. The glyph stays on the left; on the right a suggestion
is kept with one key, or a sequence is written in the IDS Workshop's editor
([ids-input](https://github.com/mkpoli/ids-input)). Every answer is written at once to
`data/review/answers.json`.

```sh
uv run python scripts/fetch_fonts.py   # once: Jigmo, which draws the sequences
cd review
bun install
bun run dev        # http://localhost:8430
```

| Deck | Items | Keys |
| --- | --- | --- |
| Proposal glyphs | printed glyphs with no IDS, least-sure first | `Z` keep the encoded character's BabelStone IDS, `1` `2` `3` keep a suggestion, `E` write, `X` can't tell |
| Model vs label | benchmark images where the reading and the label differ | `L` label, `M` model, `B` both, `E` write, `X` can't tell |

`←` and `→` move between glyphs. Each option carries the sequence drawn in Mincho by han-compose, from
the serif export the IDS Workshop publishes, and **Edit** (or Shift with the option's key) opens the
editor on that option; the editor draws the sequence as it is written.

## The editor

With a build of the [IDS Workshop](https://ids.mkpo.li/) at `build/review/workshop/` (or the folder
named by `IDS_WORKSHOP`), **Edit** opens the Workshop itself beside the glyph, and the desk reads the
sequence from the Workshop's address. The build is ids-input's own `bunx vite build demo --outDir
<folder>`, with its `ort/` folder copied in. Without one, the desk falls back to the smaller
`IdsInput` component from the `ids-input` package.

## Decks

`build/review/decks.json` is built on this machine and holds absolute image paths:

```sh
uv run python review/prepare.py read --glyphs <charsets>/glyphs
uv run python review/prepare.py decks --charsets <charsets> --dataset <benchmark dataset> --run <benchmark run> --unihan <Unihan.zip> --n891 <N891 PDF>
```

`read` strips table rules at the image edge, fits the ink with a 12 px margin and keeps the three best
beam readings. Proposal glyphs come from a folder of `<set>/<name>.png` with `*_records.json` beside
it; the current deck is the IRG proposal glyphs kept by the han-input project. A proposal whose source
reference Unihan lists, or that its withdrawal record unifies with a character, carries that character: the
desk links it to [zi.tools](https://zi.tools/) and offers its [BabelStone IDS](https://www.babelstone.co.uk/CJK/IDS.TXT)
as option `Z`.

zi.tools also has pages for many unencoded glyphs of the China Extension C1 submission,
[IRG N891](https://www.unicode.org/irg/docs/n0891-China-ExtensionC1-sub.pdf) (2002-04-18), filed under the
glyph's page, column and row there (`0891.0.01501` is page 1, column 5, row 1). That index is not published, so
`scripts/fetch_zi_n891.py` opens each glyph page of the zi.tools sets G八辅, GB18030 and GB18030v1 once, a
request a second, and writes the codes it finds to `cache/zi-tools/n891.json`. `decks --n891 <N891 PDF>` then
links each proposal with such a page, and offers that page's sequence under `Z` when it is plain IDS.
N891 glyphs found only in zi.tools' private index stay unlinked.

## Answers

`data/review/answers.json` maps an item id to `{c, ids, at}`. `c` is `known` for the IDS of the encoded character or zi.tools page, `c0`, `c1` or `c2` for a kept
suggestion, `label`, `model` or `both`, `custom` for a written sequence, or `skip`.
