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
