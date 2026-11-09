"""Report Mincho font coverage over BabelStone records and the label alphabet."""
from __future__ import annotations

import argparse
import gzip
import json
import re
from pathlib import Path

from fontTools.ttLib import TTFont

OPERATORS = set("⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽⿾⿿〾㇯")
REGIONS = re.compile(r"\([A-Z]+\)$")


def read(path: Path):
    records, alphabet = [], set()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            char, rest = line.rstrip("\n").split("\t", 1)
            records.append(char)
            for sequence in rest.split(" "):
                for token in REGIONS.sub("", sequence):
                    if token not in OPERATORS and not token.isascii() and token not in "？⬚":
                        alphabet.add(token)
    return records, alphabet


def is_han(char: str) -> bool:
    cp = ord(char)
    return (0x3400 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF or 0x20000 <= cp <= 0x3347F)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, default=Path("data/babelstone-ids.tsv.gz"))
    parser.add_argument("--noto", type=Path, default=Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"))
    parser.add_argument("--ipamj", type=Path, default=Path("cache/fonts/ipamj/ipamjm.ttf"))
    parser.add_argument("--jigmo-dir", type=Path, default=Path("cache/fonts/jigmo"))
    args = parser.parse_args()
    records, alphabet = read(args.labels)
    han = [char for char in records if is_han(char)]
    cmaps = {
        "noto": set(TTFont(args.noto, fontNumber=0).getBestCmap()),
        "ipamj": set(TTFont(args.ipamj).getBestCmap()),
        "jigmo": set(),
    }
    for path in sorted(args.jigmo_dir.glob("Jigmo*.ttf")):
        cmaps["jigmo"] |= set(TTFont(path).getBestCmap())
    out = {
        "records": len(records),
        "han_records": len(han),
        "label_alphabet": len(alphabet),
        "fonts": {
            name: {
                "han_records": sum(ord(char) in cmap for char in han),
                "label_alphabet": sum(ord(char) in cmap for char in alphabet),
            }
            for name, cmap in cmaps.items()
        },
    }
    out["union_han"] = sum(any(ord(char) in cmap for cmap in cmaps.values()) for char in han)
    out["union_alphabet"] = sum(any(ord(char) in cmap for cmap in cmaps.values()) for char in alphabet)
    out["ipamj_only_han"] = sum(ord(char) in cmaps["ipamj"] and ord(char) not in cmaps["jigmo"] for char in han)
    out["ipamj_only_alphabet"] = sum(ord(char) in cmaps["ipamj"] and ord(char) not in cmaps["jigmo"] for char in alphabet)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
