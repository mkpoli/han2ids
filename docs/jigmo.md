# Why Jigmo looks lower

The per-font test sets are not the same size. Jigmo covers the full table, so its slice contains many
more rare characters.

| font | rows | all rows exact | 1,205 shared characters |
| --- | ---: | ---: | ---: |
| Noto Serif CJK JP | 1,453 | 92.29% | 93.03% |
| IPAmj Mincho | 2,525 | 83.52% | 92.53% |
| Jigmo | 4,752 | 79.67% | 92.78% |

On the 1,205 characters covered by all three faces, Jigmo is level with Noto and above IPAmj. Its
lower overall figure is the difficulty of the extra 3,547 Jigmo rows, not a worse model on the same
characters.
