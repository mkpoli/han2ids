# v0.1 split leak

`build/font-v03/test.jsonl` has 4,752 characters.

| ids-input split | test characters present |
| --- | ---: |
| train | 4,274 (89.9%) |
| val | 449 (9.4%) |
| test | 0 |

v0.1 was trained on the ids-input train split, so 89.9% of the current test characters were seen
during training. Its 84.44% exact, the per-font v0.1 figures, the v0.1→v0.2 improvement comparison,
and the 90.17% v0.1+v0.3 oracle are not held-out results.

v0.2 and v0.3 use the disjoint `build/font-v03` character split. v0.3 at 82.88% is the clean baseline.
Use v0.2/v0.3/v0.4 only for comparisons going forward.
