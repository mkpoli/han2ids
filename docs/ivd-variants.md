# IVD and variation selectors

U+4343 has several registered forms:

| selector | form | source |
| --- | --- | --- |
| U+E0100 | ⿱𱼀缶 | Hanyo-Denshi, Moji_Joho |
| U+E0101 | ⿱𱼀缶 | Hanyo-Denshi, Moji_Joho |
| U+E0102 | ⿱爫缶 | Adobe-Japan1 |
| — | ⿱爫𠙻 | q3752 |

The data is in `data/ivd-variants.tsv`. `han2ids.status.classify(..., strict_ivd=False)`
merges these forms as `variant`; `strict_ivd=True` keeps them as separate `miss` results. The same
switch is available on `scripts/audit_status.py --strict-ivd`.

U+21275 is a separate font-design case: v0.2 prints 士, v0.1 and v0.3 print 土. It is recorded as a
variant, not a structural miss.
