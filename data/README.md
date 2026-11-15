# Data

`IDS.TXT` is BabelStone IDS with its region tags. `scripts/audit_labels.py` reads it and `data/label-overrides.tsv` records the image-specific labels, `data/font-label-overrides.tsv` records the labels that differ by font, `src/han2ids/unified-forms.tsv` lists the printed forms and the components that stand for them, and `data/equivalence-overrides.tsv` / `data/variant-overrides.tsv` record the reviewed gallery statuses. `babelstone-ids.tsv.gz` is the older compiled table without tags; the current scripts use `IDS.TXT`.

A sequence may name a component that has no code point, written `{53}`. It is read as one part of
the sequence, as a character is. Such a sequence labels a character only where BabelStone gives it
no sequence of encoded components: 1,514 characters, written with 117 of these components. The
vocabulary of v0.5 holds none of them, so that model cannot write one.

`babelstone-ids.tsv.gz` is BabelStone IDS (IDS.TXT, file date 2025-06-27) by Andrew West, public
domain, in the compiled `char<TAB>sequences` form used by the sibling ids-input project. It holds
103,825 records. The source is <https://www.babelstone.co.uk/CJK/IDS.TXT>; the file's header states
that IDS sequences are facts not eligible for copyright.
