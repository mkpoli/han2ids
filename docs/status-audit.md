# Status audit

Central classifier: exact, same tree, regional variant, miss.

| model | exact | same | variant | miss |
| --- | ---: | ---: | ---: | ---: |
| v0.1 | 7364 | 275 | 196 | 895 |
| v0.2 | 7008 | 319 | 32 | 1371 |
| v0.3 | 7237 | 394 | 33 | 1066 |

## Transitions

| from → to | exact→miss | miss→exact | miss→same | other |
| --- | ---: | ---: | ---: | ---: |
| v0.1 → v0.2 | 618 | 163 | 57 | 7892 |
| v0.2 → v0.3 | 101 | 310 | 152 | 8167 |
