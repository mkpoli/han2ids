#!/usr/bin/env python3
"""Write a page for browsing an IVD sweep: type characters, see each variant and what it was read as.

The page draws each variant as text with its selector, in the face the sweep drew it with, so it
needs the font files beside it: pass each face's files as NAME=PATH, relative to the page or absolute.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>IVD sweep</title>
<style>
/* Layout: a search field, then one block per character with its variants grouped by reading. */
:root { color-scheme: light dark; --canvas: light-dark(#f3f3f6, #111114); --surface: light-dark(#fff, #1b1b20); --ink: light-dark(#1c1c22, #ececf2);
  --muted: light-dark(#686874, #9d9daa); --line: light-dark(#e1e1e8, #2e2e36); --accent: light-dark(#2944c7, #8ea8ff); --soft: light-dark(#e9edfd, #232c4c);
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
__FACES__
* { box-sizing: border-box; }
body { margin: 0; background: var(--canvas); color: var(--ink); font: 14px/1.4 ui-sans-serif, system-ui, sans-serif; }
main { max-width: 1400px; margin: 0 auto; padding: 20px max(16px, 2vw) 48px; display: flex; flex-direction: column; gap: 16px; }
header { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; }
h1 { margin: 0; font-size: 20px; }
input { flex: 1 1 260px; min-width: 0; font: 22px "Sweep jigmo", serif; color: var(--ink); background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 8px 12px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font: 500 12px var(--mono); color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 2px 9px; background: none; }
button.chip { cursor: pointer; } button.chip[aria-pressed="true"] { color: var(--ink); border-color: var(--accent); background: var(--soft); }
section { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 16px; display: flex; flex-direction: column; gap: 14px; }
h2 { margin: 0; display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; font-size: 14px; font-weight: 600; }
h2 .char { font: 400 34px "Sweep jigmo", serif; }
h2 span { color: var(--muted); font: 500 12px var(--mono); }
.group { display: flex; flex-direction: column; gap: 8px; padding-top: 12px; border-top: 1px solid var(--line); }
.reading { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; }
.ids { font: 400 24px "Sweep jigmo", serif; overflow-wrap: anywhere; }
.count { color: var(--muted); font: 500 12px var(--mono); }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 8px; }
.tile { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 6px 4px; border: 1px solid var(--line); border-radius: 10px; }
.glyph { width: 84px; height: 84px; display: grid; place-items: center; background: #fff; color: #000; border-radius: 6px; font-size: 68px; line-height: 1; }
.tile small { color: var(--muted); font: 500 10px/1.3 var(--mono); text-align: center; overflow-wrap: anywhere; }
.none { color: var(--muted); }
</style>
</head>
<body>
<main>
  <header>
    <h1>IVD sweep</h1>
    <input id="query" type="search" lang="ja" autocomplete="off" spellcheck="false" aria-label="Characters" value="邊邉">
    <div class="chips" id="faces"></div>
  </header>
  <div class="chips" id="stats"></div>
  <div class="chips" id="most"></div>
  <div id="results"></div>
  <p class="count">Sequences: Unicode Ideographic Variation Database, __SOURCE__. Readings: han2ids __MODEL__, greedy, ink-fitted with a 12 px margin; the number is the model's uncalibrated score.</p>
</main>
<script>
const DATA = __DATA__;
const $ = id => document.getElementById(id);
const faces = new Set(DATA.faces);
function tile(row) {
  const [selector, face, ids, unified, score, same, tags] = row;
  const tile = document.createElement('div'); tile.className = 'tile'; tile.title = tags.join('\\n');
  const glyph = document.createElement('span'); glyph.className = 'glyph'; glyph.lang = 'ja';
  glyph.style.fontFamily = `"Sweep ${face}", serif`; glyph.textContent = this + String.fromCodePoint(parseInt(selector, 16));
  const a = document.createElement('small'); a.textContent = `${selector} · ${face}`;
  const b = document.createElement('small'); b.textContent = `${tags[0]}${tags.length > 1 ? ` +${tags.length - 1}` : ''} · ${score.toFixed(2)}`;
  tile.append(glyph, a, b); return tile;
}
function block(char) {
  const rows = (DATA.rows[char] || []).filter(row => faces.has(row[1]));
  const section = document.createElement('section');
  const head = document.createElement('h2');
  const big = document.createElement('span'); big.className = 'char'; big.lang = 'ja'; big.textContent = char;
  const groups = new Map();
  for (const row of rows) { if (!groups.has(row[2])) groups.set(row[2], []); groups.get(row[2]).push(row); }
  const info = document.createElement('span');
  info.textContent = `U+${char.codePointAt(0).toString(16).toUpperCase()} · ${rows.length} drawn · ${groups.size} readings`;
  head.append(big, info); section.append(head);
  if (!rows.length) { const none = document.createElement('p'); none.className = 'none'; none.textContent = 'No registered sequence drawn.'; section.append(none); return section; }
  for (const [ids, list] of [...groups].sort((x, y) => y[1].length - x[1].length)) {
    const group = document.createElement('div'); group.className = 'group';
    const reading = document.createElement('div'); reading.className = 'reading';
    const text = document.createElement('span'); text.className = 'ids'; text.lang = 'ja'; text.textContent = ids;
    const count = document.createElement('span'); count.className = 'count'; count.textContent = `${list.length}`;
    reading.append(text, count);
    const tiles = document.createElement('div'); tiles.className = 'tiles'; tiles.append(...list.map(tile, char));
    group.append(reading, tiles); section.append(group);
  }
  return section;
}
function render() {
  const chars = [...new Set([...$('query').value].filter(char => char.codePointAt(0) > 0x2E7F && !(char.codePointAt(0) >= 0xE0100 && char.codePointAt(0) <= 0xE01EF)))].slice(0, 40);
  $('results').replaceChildren(...chars.map(block));
  $('results').style.cssText = 'display:flex;flex-direction:column;gap:16px';
  try { history.replaceState(null, '', '#' + encodeURIComponent(chars.join(''))); } catch {}
}
for (const face of DATA.faces) {
  const button = document.createElement('button'); button.className = 'chip'; button.textContent = face; button.setAttribute('aria-pressed', 'true');
  button.addEventListener('click', () => { faces.has(face) ? faces.delete(face) : faces.add(face); button.setAttribute('aria-pressed', String(faces.has(face))); render(); });
  $('faces').append(button);
}
for (const text of DATA.stats) { const chip = document.createElement('span'); chip.className = 'chip'; chip.textContent = text; $('stats').append(chip); }
for (const [char, count] of DATA.most) {
  const button = document.createElement('button'); button.className = 'chip'; button.lang = 'ja'; button.textContent = `${char} ${count}`;
  button.addEventListener('click', () => { $('query').value = char; render(); }); $('most').append(button);
}
if (location.hash.length > 1) { try { $('query').value = decodeURIComponent(location.hash.slice(1)); } catch {} }
$('query').addEventListener('input', render);
render();
</script>
</body>
</html>
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep", type=Path, required=True)
    parser.add_argument("--font", action="append", default=[], help="NAME=PATH, in the order a face falls through its files")
    parser.add_argument("--source", default="IVD_Sequences.txt")
    parser.add_argument("--model", default="v0.5")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    rows = defaultdict(list)
    faces, total, same = [], 0, 0
    for line in args.sweep.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["face"] not in faces:
            faces.append(row["face"])
        rows[row["base"]].append([row["selector"][2:], row["face"], row["ids"], row["unified"], row["score"], row["as_base"],
                                  [f"{name} {tag}" for name, tag in row["registrations"]]])
        total += 1
        same += row["as_base"]
    distinct = {char: len({row[2] for row in items}) for char, items in rows.items()}
    most = sorted(distinct.items(), key=lambda item: (-item[1], item[0]))[:40]
    stats = [f"{total:,} readings", f"{len(rows):,} characters", f"{sum(1 for count in distinct.values() if count > 1):,} characters with more than one reading",
             f"{100 * same / max(1, total):.1f}% read as the base character"]
    families = defaultdict(list)
    for item in args.font:
        name, path = item.split("=", 1)
        families[name].append(path if "://" in path or not os.path.isabs(path) else Path(path).as_uri())
    css = "\n".join(f'@font-face {{ font-family: "Sweep {name}"; src: {", ".join(f"url(\"{path}\")" for path in paths[:1])}; }}' if len(paths) == 1 else
                    "\n".join(f'@font-face {{ font-family: "Sweep {name}"; src: url("{path}"); unicode-range: {span}; }}'
                              for path, span in zip(paths, ("U+0-FFFF, U+E0100-E01EF", "U+20000-2FFFF", "U+30000-3FFFF")))
                    for name, paths in families.items())
    data = json.dumps({"faces": faces, "rows": rows, "most": most, "stats": stats}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    args.output.write_text(PAGE.replace("__FACES__", css).replace("__DATA__", data).replace("__SOURCE__", args.source).replace("__MODEL__", args.model), encoding="utf-8")
    print(f"{args.output}\t{total} readings, {len(rows)} characters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
