# Glyph face

`han2ids-glyphs.woff2` draws the sequence text, including components outside the BMP that the
reader's installed fonts often miss.

- Source: [Jigmo](https://kamichikoichi.github.io/jigmo/) 2025-09-12 by Koichi Kamichi, CC0 1.0.
  The three volumes (`Jigmo.ttf`, `Jigmo2.ttf`, `Jigmo3.ttf`) were subset to their own characters
  first and merged, then subset to the checkpoint's 10,419 output characters, including the IDS
  operators. Every output character is covered.
- Licence: CC0 1.0; the text is in `LICENSES/Jigmo-CC0.txt` in the repository root.
- SHA-256: `0db70518dc987678b74e224498c628188366fa29c23bb89d541ca4e70361406c`.
- Size: 1.8 MB.

The subset was made with `fontTools.merge.Merger` and `pyftsubset --flavor=woff2`, with layout
features and hinting dropped. The UI keeps the system sans face; only readings use this file.
