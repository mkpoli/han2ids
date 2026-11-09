# Status audit

Central classifier: exact, same tree, regional variant, miss.

| model | exact | same | variant | miss |
| --- | ---: | ---: | ---: | ---: |
| v0.1 | 7364 | 275 | 195 | 896 |
| v0.2 | 7008 | 319 | 30 | 1373 |
| v0.3 | 7237 | 394 | 33 | 1066 |

## Transitions

| from → to | exact→miss | miss→exact | miss→same | other |
| --- | ---: | ---: | ---: | ---: |
| v0.1 → v0.2 | 620 | 164 | 57 | 7889 |
| v0.2 → v0.3 | 101 | 312 | 152 | 8165 |
