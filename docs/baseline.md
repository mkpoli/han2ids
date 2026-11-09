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
| v0.2, 8,730 mixed-font rows | 82.45% | 100% |
| v0.1 on the same rows | 74.27% | 100% |

| font | v0.2 | v0.1 |
| --- | ---: | ---: |
| Noto Serif CJK JP | 92.02% | 92.15% |
| IPAmj Mincho | 82.69% | 84.32% |
| Jigmo family | 79.40% | 63.47% |

The gain is on Jigmo (+15.9 points); IPAmj gives up 1.6 points and Noto is flat. v0.2 is the default
checkpoint.
