# Font-held-out pilot

A first from-scratch run with IPAmj held out.

## Setup

- 20,249 train characters, rendered in Noto Serif CJK JP and the Jigmo family (two images each).
- 2,223 IPAmj characters for validation and 2,223 for test; IPAmj was not in training.
- 35.2M ViT-S/16 + 4-layer decoder, ImageNet-21k encoder, four epochs on the 40,498 training images.
- Labels: BabelStone's first usable IDS per character.

## Results

| model | training | Noto test | Jigmo test | IPAmj test |
| --- | --- | ---: | ---: | ---: |
| `han2ids-v0.1` | 85,776 serif-export images | 91.8% | 70.0% | 89.7% |
| font pilot | 40,498 images | 81.9% | 81.7% | 81.1% |

The pilot raises Jigmo by 11.7 points, but loses Noto and IPAmj. It has a quarter of the baseline's
characters, so this is not a clean comparison of font diversity. It does show that style-specific
training moves the font it trained on, and that a held-out Mincho face reaches 81% from 20k
characters.

## Next

1. Run the same recipe on all 97,680 Han records with the full font set.
2. Train a second model with IPAmj included and compare it with this held-out run.
3. Add tight-crop and scale augmentation; the current renders are clean em boxes.

The script is `scripts/pilot_fonts.py`; the result is `docs/pilot-font-results.json`. The pilot
checkpoint is local (`models/han2ids-font-pilot.pt`, ignored) and is not the shipped model.


## Full font run

The production v0.2 model used 95,927 Han characters (97,680 BabelStone Han records, 1,753 without a usable sequence) and every available face: 159,516 training
images, 8,714 validation and 8,730 test images. Noto covers 29,847 rows, IPAmj 52,518 and Jigmo
97,680. Four epochs, batch 32, the same 35.2M architecture, decoder from scratch and ImageNet-21k
encoder.

| test | v0.2 | v0.1 |
| --- | ---: | ---: |
| overall, corrected labels | 82.59% | 74.27% |
| Noto | 92.15% | 92.15% |
| IPAmj | 82.85% | 84.32% |
| Jigmo | 79.52% | 63.47% |

Jigmo gains 15.9 points; IPAmj loses 1.6; Noto is unchanged. The result is in
`docs/full-font-results.json`; the local checkpoint is `models/han2ids-v0.2.pt`.

## v0.3

v0.3 retrains on a common em-box rendering: a 200-unit em box with the baseline at 0.88 em, cropped to
224. That removes the per-font anchor offset and the bottom clipping of the earlier renders. The labels
carry the three image overrides.

| test | v0.3 | v0.2, same renders |
| --- | ---: | ---: |
| exact | 82.91% | 80.24% |
| same tree | 86.37% | |
| valid | 100% | 99.97% |

Jigmo gains 3.91 exact points over v0.2 on the same renders. The checkpoint is
`models/han2ids-v0.3.pt`; the training script is `scripts/train_fonts_v3.py`.
