# Models

`han2ids-v0.3.pt` is the working checkpoint (v0.1 and v0.2 files are kept for comparison) (135 MB). It is not committed; keep it in this folder.

It is a `GlyphIDS` state dict with `itos` and `args` (`encoder`, `max_len`). The architecture is the
ViT-S/16 encoder and 4-layer decoder in `src/han2ids/model.py`.

Publish the checkpoint separately when it is ready; the repository only carries the loader.
