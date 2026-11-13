# Review desk

A local page for reviewing what han2ids reads. The glyph stays on the left; on the right a suggestion
is kept with one key, or a sequence is written in the IDS Workshop's editor
([ids-input](https://github.com/mkpoli/ids-input)). Every answer is written at once to
`data/review/answers.json`.

```sh
uv run python scripts/fetch_fonts.py   # once: Jigmo, which draws the sequences
mkdir -p build/review && ln -sfn <han-compose checkout>/js build/review/han-compose
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

han-compose's composer is not on npm. ids-input reads it from a han-compose checkout at the commit its
`.github/actions/composer/action.yml` pins, and so does the desk: `build/review/han-compose` links to that
checkout's `js/` folder, built with `bun install && bun run data && bun run types`.

## The editor

With a build of the [IDS Workshop](https://ids.mkpo.li/) at `build/review/workshop/` (or the folder
named by `IDS_WORKSHOP`), **Edit** opens the Workshop's editor page (`editor.html`: one sequence, no
tabs or site menus) beside the glyph, and the page posts each change back to the desk. The build is
ids-input's own `bunx vite build demo --outDir <folder>`, with its `ort/` folder copied in. Without
one, the desk falls back to the smaller `IdsInput` component from the `ids-input` package.

## Decks

`build/review/decks.json` is built on this machine and holds absolute image paths:

```sh
uv run python review/prepare.py read --glyphs <charsets>/glyphs
uv run python review/prepare.py decks --charsets <charsets> --dataset <benchmark dataset> --run <benchmark run> --unihan <Unihan.zip>
```

`read` strips table rules at the image edge, fits the ink with a 12 px margin and keeps the three best
beam readings. Proposal glyphs come from a folder of `<set>/<name>.png` with `*_records.json` beside
it; the current deck is the IRG proposal glyphs kept by the han-input project. A proposal whose source
reference Unihan lists, or that its withdrawal record unifies with a character, carries that character: the
desk links it to [zi.tools](https://zi.tools/) and offers its [BabelStone IDS](https://www.babelstone.co.uk/CJK/IDS.TXT)
as option `Z`.

## Answers

`data/review/answers.json` maps an item id to `{c, ids, at}`. `c` is `known` for the encoded character's IDS, `c0`, `c1` or `c2` for a kept
suggestion, `label`, `model` or `both`, `custom` for a written sequence, or `skip`.
