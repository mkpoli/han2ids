# Status audit

Central classifier: exact, same tree, regional variant, miss.

| model | exact | same | variant | miss |
| --- | ---: | ---: | ---: | ---: |
| v0.1 | 7371 | 275 | 224 | 860 |
| v0.2 | 7007 | 317 | 46 | 1360 |
| v0.3 | 7236 | 394 | 48 | 1052 |

## Transitions

| from → to | exact→miss | miss→exact | miss→same | other |
| --- | ---: | ---: | ---: | ---: |
| v0.1 → v0.2 | 618 | 146 | 54 | 7912 |
| v0.2 → v0.3 | 101 | 311 | 152 | 8166 |
