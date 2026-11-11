# Continuation experiment

The [training script](../scripts/train_accuracy_experiment.py) compares continuation from a trusted checkpoint using cached images or unclipped, ink-fitted renders. Validation reports agreement with existing unreviewed labels; [v0.4 was selected on this split](../scripts/train_fonts_v4.py#L109-L115) and its [vocabulary includes held-out label tokens](../scripts/train_fonts_v3.py#L165-L168).

## Run

Install the training extra, prepare the `font-v03` cache and v0.4 checkpoint, and set the font paths before running:

```sh
uv sync --extra train --extra dev
gpu-check --venv .
systemd-run --user --scope --unit han2ids-accuracy-run --slice batch.slice \
  -p MemorySwapMax=0 --same-dir -- env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  uv run python scripts/train_accuracy_experiment.py \
  --cache build/font-v03 --init models/han2ids-v0.4.pt --out-dir build/accuracy-run \
  --font "noto=0=$NOTO_FONT" --font "ipamj=0=$IPAMJ_FONT" \
  --font "jigmo=0=$JIGMO_FONT" --font "jigmo=0=$JIGMO2_FONT" \
  --font "jigmo=0=$JIGMO3_FONT" --render clean --augment \
  --epochs 2 --batch-size 1 --accumulation-steps 32 --eval-batch-size 1 \
  --encoder-lr 5e-5 --decoder-lr 2.5e-4 --gpu-fraction 0.07 --min-free-gib 2.3 \
  --seed 17 --sample-seed 8128 --max-train-characters 2048 --max-val-characters 256
```

`--render legacy` uses cached pixels; `--render clean` uses the first listed face covering each character and changes framing, scale and centering together. Augmentation refits the glyph at sampled sizes and positions and may apply blur and contrast changes. Omit `--augment` for an unaugmented run and omit character limits to use the full train and validation splits.

## Outputs

| File | Contents |
| --- | --- |
| `settings.json` | Configuration, selected software versions and input, font and code hashes; home paths use `$HOME`. |
| `train_rows.jsonl`, `val_rows.jsonl` | Selected rows and resolved labels. |
| `val_epoch_<n>_<view>.jsonl` | Paired predictions on legacy and clean validation images. Epoch 0 uses the initial checkpoint. |
| `metrics.jsonl` | Training loss and validation label agreement by epoch and font. |
| `epoch_<n>.pt` | Model weights for an epoch; optimizer and RNG state are not saved. |
| `artifacts.json` | Output file hashes. |

The output directory must be new. Each continuation starts a new optimizer and warmup schedule. Set the example's learning rates and GPU limits for the experiment and machine; the fraction limits the PyTorch allocator, not the CUDA context or other allocations. Equal manifest and array lengths do not prove the original cache rows correspond, and checkpoint files must be trusted.
