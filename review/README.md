# Review desk

A local page for reviewing what han2ids reads. The glyph stays on the left; on the right a suggestion
is kept with one key, or a sequence is written in the IDS Workshop's editor
([ids-input](https://github.com/mkpoli/ids-input)). Every answer is written at once to
`data/review/answers.json`.

```sh
cd review
bun install
bun run dev        # http://localhost:8430
```

| Deck | Items | Keys |
| --- | --- | --- |
| Proposal glyphs | printed glyphs with no IDS, least-sure first | `1` `2` `3` keep a suggestion, `E` write, `X` can't tell |
| Model vs label | benchmark images where the reading and the label differ | `L` label, `M` model, `B` both, `E` write, `X` can't tell |

`←` and `→` move between glyphs.

## Decks

`build/review/decks.json` is built on this machine and holds absolute image paths:

```sh
uv run python review/prepare.py read --glyphs <charsets>/glyphs
uv run python review/prepare.py decks --charsets <charsets> --dataset <benchmark dataset> --run <benchmark run>
```

`read` strips table rules at the image edge, fits the ink with a 12 px margin and keeps the three best
beam readings. Proposal glyphs come from a folder of `<set>/<name>.png` with `*_records.json` beside
it; the current deck is the IRG proposal glyphs kept by the han-input project.

## Answers

`data/review/answers.json` maps an item id to `{c, ids, at}`. `c` is `c0`, `c1` or `c2` for a kept
suggestion, `label`, `model` or `both`, `custom` for a written sequence, or `skip`.
