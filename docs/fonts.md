# Fonts

han2ids is deliberately Mincho / 宋体 only. Kai, sans and handwriting are out of scope.

## Coverage of the labels

The serif training set has 97,680 Han records and 10,398 distinct characters written in its labels.

For the 97,680 Han records, Jigmo covers all 97,680; IPAmj covers 52,518 and adds none. For the 10,398
label characters, Jigmo covers all; IPAmj covers 8,379 and adds none.

| font | characters covered |
| --- | ---: |
| Noto Serif CJK JP | 7,272 |
| IPAmj Mincho 006.01 | 8,379 |
| Jigmo 2025-09-12 | 10,398 |
| union | 10,398 |

Jigmo covers every record and every label character. IPAmj adds **no character Jigmo lacks**; its
value is a second Mincho style, not extra coverage. The "IPAmj only" count is 0. `scripts/coverage.py`
also reports the wider BabelStone table, where Tangut components pull the alphabet count above the
10,398 used by the serif set.

This table is reproduced by `python scripts/coverage.py`.

## Terms

- Noto Serif CJK JP, SIL OFL 1.1.
- IPAmj Mincho, IPA Font License v1.0, `LICENSES/IPA-Font-License.txt`.
- Jigmo, CC0 1.0, `LICENSES/Jigmo-CC0.txt`.
