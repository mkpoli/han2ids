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

## Printed forms

`han2ids-forms.woff2` draws 鄕 with its variation selectors U+E0101 and U+E0102, which the merged
face above does not carry. The stylesheet lists it first, limited to U+9115 and the selectors.

- Source: `Jigmo.ttf` from the same Jigmo release, CC0 1.0.
- Made with `pyftsubset Jigmo.ttf --unicodes=U+9115,U+E0101,U+E0102 --flavor=woff2 --no-hinting --layout-features=''`.
- SHA-256: `bba4a179586b8b5d14248625f1c8f5d274bd97bf836a44d1f32e70844f74cc9d`.
- Size: 1.3 kB.
