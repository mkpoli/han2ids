#!/usr/bin/env python3
"""Find the zi.tools page of each IRG N891 glyph.

zi.tools files the China Extension C1 submission (IRG N891) under its own position code,
`0891.0.PPCRR` (page, column, row of the document), and keeps that index private. A glyph's page
shows its code, so this walks the zi.tools sets that hold N891 glyphs, opens each glyph's page
once, and keeps the codes it finds. One request a second; every answer is cached, so a stopped
run resumes where it left off.

Writes cache/zi-tools/n891.json: N891 code -> the sequence that addresses its zi.tools page.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "cache" / "zi-tools"
API = "https://zi.tools/api"
SETS = ("g_8f", "gb_a", "gb_a_v1")
HEADERS = {"User-Agent": "han2ids-review/1.0"}


def get(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as response:
        return json.load(response)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    seen_path = OUT / "pages.jsonl"
    seen = {}
    if seen_path.exists():
        lines = seen_path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:  # a record cut short by an interrupted run; its page is fetched again
                continue
            seen[row["ids"]] = row["ma"]
        seen_path.write_text("".join(json.dumps({"ids": text, "ma": ma}, ensure_ascii=False) + "\n" for text, ma in seen.items()), encoding="utf-8")
    sequences = []
    for name in SETS:
        path = OUT / f"set-{name}.json"
        if not path.exists():
            path.write_text(json.dumps(get(f"{API}/ma/ma/{name}.json"), ensure_ascii=False), encoding="utf-8")
            time.sleep(args.delay)
        sequences += [row[1] for row in json.loads(path.read_text(encoding="utf-8"))["rows"]]
    todo = [text for text in dict.fromkeys(sequences) if text not in seen]
    print(f"{len(seen)} cached, {len(todo)} to fetch", flush=True)
    failed = 0
    with open(seen_path, "a", encoding="utf-8") as log:
        for at, text in enumerate(todo):
            try:
                body = get(f"{API}/zi/{urllib.parse.quote(text, safe='')}")
                ma = json.loads(((body.get("yi") or {}).get("kv") or {}).get("ma") or "[]")
            except Exception as error:  # a failed page is retried on the next run
                print(f"skip {text}: {error}", flush=True)
                failed += 1
                time.sleep(args.delay * 5)
                continue
            seen[text] = ma
            log.write(json.dumps({"ids": text, "ma": ma}, ensure_ascii=False) + "\n")
            log.flush()
            if at % 100 == 0:
                print(f"{at}/{len(todo)}", flush=True)
            time.sleep(args.delay)
    codes = {}
    for text, ma in seen.items():
        for entry in ma:
            if entry[0] == "IRGN" and str(entry[1]).startswith("0891."):
                codes[entry[1]] = text
    (OUT / "n891.json").write_text(json.dumps(dict(sorted(codes.items())), ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{OUT / 'n891.json'}\t{len(codes)} N891 glyphs with a zi.tools page", flush=True)
    if failed:
        print(f"{failed} pages failed; run again to fetch them", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
