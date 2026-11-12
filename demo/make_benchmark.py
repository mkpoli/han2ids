#!/usr/bin/env python3
"""Write the benchmark page's data from the published scores in benchmark/results."""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmark" / "results"
TARGET = ROOT / "demo" / "static" / "benchmark.json"
TRACKS = ("clean", "reviewed", "styles", "candidates")
MEASURES = {"exact": "raw_exact", "sameAxis": "structural_match", "family": "family_match",
            "f1": "component_f1", "tree": "tree_edit_similarity"}
# docs/leak.md: 89.9% of the test characters were in v0.1's training split.
OVERLAP = {"v0.1"}


def load(track: str, pattern: str) -> dict:
    path, = (RESULTS / track / "scores").glob(pattern)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def reader(run: str) -> dict:
    name = run.split("-", 1)[1]
    version = re.fullmatch(r"han-v(\d)(\d+)", name)
    if version:
        label = f"v{version.group(1)}.{version.group(2)}"
        return {"id": label, "name": f"han2ids {label}", "group": "han2ids", "overlap": label in OVERLAP}
    if name == "han-pilot":
        return {"id": "pilot", "name": "han2ids font pilot", "group": "han2ids", "overlap": False}
    if name == "glyphstudio":
        return {"id": "glyphstudio", "name": "GlyphStudio 0.1.0", "group": "external", "overlap": False}
    raise ValueError(f"unknown run {run}")


def percent(value: float) -> float:
    return round(value * 100, 2)


def main() -> int:
    readers: dict[str, dict] = {}
    tracks = []
    for track in TRACKS:
        scores = load(track, "*-scores*.json.gz")
        selective = load(track, "*-selective-summary.json.gz")
        rows = {}
        for run, body in scores["runs"].items():
            who = reader(run)
            readers.setdefault(who["id"], who)
            aggregate = body["aggregate"]
            sensitivity = selective["runs"][run]["aggregate"]["scores"]
            low, high = ("selective_recall_at_5", "selective_recall_at_5_upper") if track == "candidates" \
                else ("selective_hit", "selective_upper")
            rows[who["id"]] = {
                **{measure: percent(aggregate["scores"][key]["character_macro"]) for measure, key in MEASURES.items()},
                **({"top5": percent(aggregate["scores"]["structural_recall_at_5"]["character_macro"])}
                   if track == "candidates" else {}),
                "expanded": [percent(sensitivity[low]["character_macro"]), percent(sensitivity[high]["character_macro"])],
            }
        counts = next(iter(scores["runs"].values()))["aggregate"]
        tracks.append({"id": track, "images": counts["sample_count"], "characters": counts["character_count"],
                       "reviewed": track == "reviewed", "rows": rows})
    order = sorted(readers.values(), key=lambda who: (who["group"] != "han2ids", who["id"] != "pilot", who["id"]))
    TARGET.write_text(json.dumps({"readers": order, "tracks": tracks}, ensure_ascii=False, indent=1) + "\n")
    print(f"{TARGET}\t{len(order)} readers, {len(tracks)} tracks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
