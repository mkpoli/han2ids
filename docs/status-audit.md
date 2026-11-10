# Status audit

Central classifier: exact, same tree, regional variant, miss.

| model | exact | same | variant | miss |
| --- | ---: | ---: | ---: | ---: |
| v0.1 | 7372 | 275 | 232 | 851 |
| v0.2 | 7008 | 317 | 51 | 1354 |
| v0.3 | 7235 | 394 | 50 | 1051 |

## Transitions

| from → to | exact→miss | miss→exact | miss→same | other |
| --- | ---: | ---: | ---: | ---: |
| v0.1 → v0.2 | 616 | 140 | 54 | 7920 |
| v0.2 → v0.3 | 102 | 309 | 152 | 8167 |
