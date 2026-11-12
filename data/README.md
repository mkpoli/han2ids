# Data

`IDS.TXT` is BabelStone IDS with its region tags. `scripts/audit_labels.py` reads it and `data/label-overrides.tsv` records the image-specific labels, `data/font-label-overrides.tsv` records the labels that differ by font, `data/unified-forms.tsv` lists the printed forms and the components that stand for them, and `data/equivalence-overrides.tsv` / `data/variant-overrides.tsv` record the reviewed gallery statuses. `babelstone-ids.tsv.gz` is the older compiled table without tags; the current scripts use `IDS.TXT`.

`babelstone-ids.tsv.gz` is BabelStone IDS (IDS.TXT, file date 2025-06-27) by Andrew West, public
domain, in the compiled `char<TAB>sequences` form used by the sibling ids-input project. It holds
103,825 records. The source is <https://www.babelstone.co.uk/CJK/IDS.TXT>; the file's header states
that IDS sequences are facts not eligible for copyright.
