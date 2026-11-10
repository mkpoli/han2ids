"""Count every v0.1/v0.2/v0.3 status and every transition, once."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from han2ids.status import classify

MODELS = {
    'v0.1': [json.loads(line) for line in (ROOT / 'build/improvements/v01.jsonl').read_text().splitlines()],
    'v0.2': [json.loads(line) for line in (ROOT / 'build/gallery-v02/predictions.jsonl').read_text().splitlines()],
    'v0.3': [json.loads(line) for line in (ROOT / 'build/gallery-v3/predictions.jsonl').read_text().splitlines()],
}
parser = argparse.ArgumentParser()
parser.add_argument("--strict-ivd", action="store_true")
args = parser.parse_args()
status = {}
for name, rows in MODELS.items():
    status[name] = [(row, classify(row['char'], row['font'], row['pred'], row['ids'], strict_ivd=args.strict_ivd)) for row in rows]
    counts = Counter(kind for _, kind in status[name])
    print(name, dict(counts), {k: round(v / len(rows) * 100, 2) for k, v in counts.items()})

report = ['# Status audit', '', 'Central classifier: exact, same tree, regional variant, miss.', '']
report.append('| model | exact | same | variant | miss |')
report.append('| --- | ---: | ---: | ---: | ---: |')
for name in ('v0.1', 'v0.2', 'v0.3'):
    counts = Counter(kind for _, kind in status[name])
    report.append(f"| {name} | {counts['exact']} | {counts['same']} | {counts['variant']} | {counts['miss']} |")
report += ['', '## Transitions', '', '| from → to | exact→miss | miss→exact | miss→same | other |', '| --- | ---: | ---: | ---: | ---: |']
for prev, curr in [('v0.1', 'v0.2'), ('v0.2', 'v0.3')]:
    other = {(row['char'], row['font']): kind for row, kind in status[curr]}
    transitions = Counter()
    for row, kind in status[prev]:
        transitions[(kind, other[(row['char'], row['font'])])] += 1
    report.append(f"| {prev} → {curr} | {transitions[('exact','miss')]} | {transitions[('miss','exact')]} | {transitions[('miss','same')]} | {sum(transitions.values()) - sum(transitions[k] for k in [('exact','miss'),('miss','exact'),('miss','same')])} |")
    print(prev, curr, dict(transitions))
(ROOT / 'docs/status-audit.md').write_text('\n'.join(report) + '\n')
