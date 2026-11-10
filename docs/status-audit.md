# Status audit

Central classifier: exact, same tree, regional variant, miss.

| model | exact | same | variant | miss |
| --- | ---: | ---: | ---: | ---: |
| v0.1 | 7373 | 275 | 231 | 851 |
| v0.2 | 7009 | 317 | 50 | 1354 |
| v0.3 | 7235 | 394 | 51 | 1050 |

## Transitions

| from → to | exact→miss | miss→exact | miss→same | other |
| --- | ---: | ---: | ---: | ---: |
| v0.1 → v0.2 | 616 | 140 | 54 | 7920 |
| v0.2 → v0.3 | 103 | 309 | 152 | 8166 |
