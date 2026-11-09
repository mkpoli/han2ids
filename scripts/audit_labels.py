"""Audit image-specific label fixes and the 争/爭 families."""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from han2ids.labels import base_labels, japanese_labels, read, read_overrides

records = read(ROOT / "data/IDS.TXT")
overrides = read_overrides(ROOT / "data/label-overrides.tsv")
current = base_labels(ROOT / "data/IDS.TXT", ROOT / "data/label-overrides.tsv")
japanese = japanese_labels(ROOT / "data/IDS.TXT", ROOT / "data/label-overrides.tsv")
old = {}
with gzip.open(ROOT / "data/babelstone-ids.tsv.gz", "rt", encoding="utf-8") as handle:
    for line in handle:
        if line.strip() and not line.startswith("#"):
            char, rest = line.rstrip("\n").split("\t", 1)
            for candidate in rest.split(" "):
                candidate = candidate.split("(")[0]
                if candidate and candidate[0] in "⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽⿾⿿〾㇯" and not any(t in candidate for t in "{&？?["):
                    old[char] = candidate
                    break

changed_by_override = [(char, old.get(char), current[char], overrides[char][1]) for char in overrides if char in current]
changed_by_region = [(char, current.get(char), japanese[char], [s.regions for s in records[char] if s.text == japanese[char]][:1]) for char in current if japanese.get(char) and japanese[char] != current[char]]
competition = []
for char, sequences in records.items():
    if any("争" in s.text or "爭" in s.text for s in sequences):
        note = overrides.get(char, ("", ""))[1]
        if char == "崢":
            note = "kept as ⿰山爭; the model emits ⿰山争; review open, not treated as exact"
        competition.append((char, current.get(char), [(s.text, s.regions) for s in sequences], note))

lines = ["# Label audit", "",
         "## Image-specific overrides", "",
         "| char | before | after | note |", "| --- | --- | --- | --- |"]
for char, before, after, note in changed_by_override:
    lines.append(f"| {char} | {before} | {after} | {note} |")
lines += ["", f"## 争 / 爭 families ({len(competition)} characters)", "",
          "The current label is the first BabelStone sequence unless an override above applies. The alternatives and region tags are listed for review. 淨, 靜, 掙, 睜 and 箏 use 爭 in Japanese. 崢 remains an open case: the model emits 争 while the source has 爭, so it is not counted as exact.", "",
          "| char | current | sequences | note |", "| --- | --- | --- | --- |"]
for char, value, sequences, note in competition:
    lines.append(f"| {char} | {value} | {' · '.join(f'{text} ({regions})' for text, regions in sequences)} | {note} |")
lines += ["", f"## Japanese-tagged alternatives that differ from the current label ({len(changed_by_region)} characters)", "",
          "These were not applied wholesale: many are packed versus expanded spellings of the same tree. The table is the review list.", "",
          "| char | current | J-tagged |", "| --- | --- | --- |"]
for char, current_text, japanese_text, regions in changed_by_region[:200]:
    lines.append(f"| {char} | {current_text} | {japanese_text} |")
(ROOT / "docs/label-audit.md").write_text("\n".join(lines) + "\n")

# Impact of the current image-specific labels on the published v0.2 predictions.
pred = [json.loads(line) for line in (ROOT / "build/gallery-v2/predictions.jsonl").read_text().splitlines()]
old_exact = sum(row["exact"] for row in pred)
new_exact = sum(row["pred"] == current.get(row["char"], row["ids"]) for row in pred)
changed = [(row["char"], row["font"], row["ids"], current.get(row["char"], row["ids"]), row["pred"]) for row in pred if current.get(row["char"], row["ids"]) != row["ids"]]
(ROOT / "docs/label-impact.json").write_text(json.dumps({
    "test_rows": len(pred), "old_exact": old_exact / len(pred), "new_exact": new_exact / len(pred),
    "changed_labels": len(changed), "changed": changed}, ensure_ascii=False, indent=1) + "\n")
print("overrides", len(changed_by_override), "competition", len(competition), "J alternatives", len(changed_by_region))
print("test exact", old_exact / len(pred), "->", new_exact / len(pred), "changed rows", len(changed))
for row in changed[:20]:
    print(row)
