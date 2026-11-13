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

v0.3 retrains on a common rendering: the glyph is drawn at 224 px with its baseline at a fixed
height, and a 200 px window is cut out and scaled to 224. That removes the per-font anchor offset of
the earlier renders. The window is smaller than the em box, so it clips ink on at least one side of
8,719 of the 8,730 test images (`benchmark/RESULTS.md`, original crop audit). The labels
carry the four image overrides.

| test | v0.3 | v0.2, same renders |
| --- | ---: | ---: |
| exact | 82.90% | 80.24% |
| same tree | 86.48% | |
| valid | 100% | 99.97% |

The recorded run (`build/font-v03/results.json`) is 82.90%; other notes give 82.88% and 82.93% for
the same checkpoint. Jigmo gains 3.91 exact points over v0.2 on the same renders. The checkpoint is
`models/han2ids-v0.3.pt`; the training script is `scripts/train_fonts_v3.py`.

## v0.5

v0.5 continues v0.4 for three epochs at one fifth of its learning rates (encoder 1e-5, decoder 5e-5).
Three things change in the data:

- **Printed-form labels.** The 鄉 family is labelled by the form each face prints
  (`docs/font-variants.md`); 鄕 with U+E0101 and with U+E0102 are output tokens.
- **Ink-fitted renders.** Half of the rows are drawn again from the face with the ink centred and
  scaled to a margin of 6 to 30 px, the framing of the clean benchmark track and of a cropped glyph.
  The other half keeps the cached em-box image.
- **Composed glyphs.** A fifth of each batch is two glyphs of one face placed side by side or
  stacked and labelled `⿰AB` or `⿱AB`. Half of the components come from those that fewer than six
  training labels contain, and a quarter of the compositions hold a form of 鄉. A composition whose
  unified reading is a validation or test label is never drawn.

Agreement with the labels on the 8,714 validation images:

| | cached em-box view | ink-fitted view | rows with a component no training label has (341) |
| --- | ---: | ---: | ---: |
| v0.4 | 84.91% | 83.50% | 0.0% |
| ink-fitted renders only, 3 epochs | 84.27% | 84.32% | 0.0% |
| v0.5: ink-fitted renders and composed glyphs | **86.11%** | **86.02%** | 2.1% |

The composed glyphs carry the gain; ink-fitted renders alone trade cached-view agreement for
ink-fitted agreement. Each arm ran once with seed 17, and the validation split chose the checkpoint,
so the held-out numbers are the ones in `benchmark/RESULTS.md`: 83.77% exact on the clean track
against v0.4's 80.05%, a paired difference of 3.72 points (interval 3.09 to 4.31).

On the three test images of 䦳, v0.5 reads `⿵門鄉` for Noto, `⿵門鄕󠄂` for IPAmj and
`⿵門鄕󠄁` for Jigmo, each with the unified reading `⿵門鄉`; v0.4 read `⿵門鄉` for all three.

The script is `scripts/train_v5.py`; per-epoch metrics are in `docs/v0.5-results.json`. The two arms
shared the GPU with each other and another job; an epoch took 9 to 34 minutes.
