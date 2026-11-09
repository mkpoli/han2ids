# Baselines

## v0.1

`models/han2ids-v0.1.pt` is the 35.2M ViT-S/16 encoder plus 4-layer decoder trained on the serif
split in the sibling `ids-input` project.

| | |
| --- | ---: |
| test characters | 4,839 |
| exact IDS | 80.10% |
| valid IDS | 99.98% |
| root operator | 97.09% |

By depth: 84.98% at depth 1, 49.12% at depth 2, 28.57% at depth 3, 12.50% at depth 4 or more.

A zero-shot font test on 653 characters covered by four faces:

| font | exact |
| --- | ---: |
| Noto Serif CJK JP | 87.9% |
| Yu Mincho | 87.7% |
| MingLiU (Taiwanese Song) | 78.7% |
| DFKai-SB (Taiwanese Kai) | 41.2% |

The Kai result is why Kai is out of scope. A naive mixed fine-tune on 5,000 characters raised DFKai
to 64.6% but dropped Noto to 78.9%; style-balanced training is the next experiment, not a small
fine-tune.


## v0.2

The full Mincho model, trained on 176,960 images (Noto, IPAmj and Jigmo) for 97,680 Han records.

| test | exact | valid |
| --- | ---: | ---: |
| v0.2, 8,730 mixed-font rows, corrected labels | 82.59% | 100% |
| v0.1 on the same rows | 74.27% | 100% |

| font | v0.2 | v0.1 |
| --- | ---: | ---: |
| Noto Serif CJK JP | 92.15% | 92.15% |
| IPAmj Mincho | 82.85% | 84.32% |
| Jigmo family | 79.52% | 63.47% |

The gain is on Jigmo (+15.9 points); IPAmj gives up 1.6 points and Noto is flat. v0.2 is the default
checkpoint.

## v0.3

The common em-box model: 176,965 images over 95,927 Han characters, four epochs. The renderer fixes the
shared baseline; the labels use the three image overrides and leave 崢 as a reviewed miss.

| test | exact | same tree | valid |
| --- | ---: | ---: | ---: |
| v0.3, 8,730 mixed-font rows | 82.90% | 86.36% | 100% |
| v0.2 on the same em-box renders | 80.23% | | 99.97% |

| font | v0.3 exact | v0.2 exact, same renders |
| --- | ---: | ---: |
| Noto Serif CJK JP | 92.29% | 91.19% |
| IPAmj Mincho | 83.60% | 82.38% |
| Jigmo family | 79.65% | 75.74% |

v0.3 is the default checkpoint.
