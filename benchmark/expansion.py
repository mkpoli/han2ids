"""Experimental dictionary-expansion sensitivity; not image-gold correctness.

Sources are external, user-specified and SHA-256 pinned. CHISE IDS TSV uses
``U+XXXX<TAB>character<TAB>IDS[<TAB>IDS...]`` for BMP rows and
``U-XXXXXXXX<TAB>character<TAB>IDS[<TAB>IDS...]`` for supplementary rows;
comments start with ``;;``.
See https://gitlab.chise.org/CHISE/ids (CHISE IDS data: GPL-2.0-or-later;
verify the license of each specific supplied source). No external data is
bundled. Entity references and multiple possible decompositions are never
resolved. An optional explicit policy may match component variants at selected
normalized-tree positions; it does not alter expansion or compute closure.
Expansion is provisional: a shared IDS does not establish visual identity.
Single-definition collision statistics do not cover transitive expansion.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Optional, Sequence

from .ids_evaluator import FamilyRule, Leaf, Node, Tree, _family_match, normalize, parse_ids


@dataclass(frozen=True)
class SourceSpec:
    path: Path
    sha256: str
    provenance: str
    license: str


@dataclass(frozen=True)
class ExpansionIndex:
    definitions: dict[str, Tree]
    opaque_reasons: dict[str, str]
    metadata: dict


@dataclass(frozen=True)
class SideResult:
    status: str
    trace: tuple[dict, ...]
    reason: str = ""


@dataclass(frozen=True)
class Comparison:
    match: Optional[bool]
    prediction: SideResult
    reference: SideResult
    family_match: Optional[bool] = None


def load_sources(sources: list[SourceSpec]) -> ExpansionIndex:
    """Load pinned CHISE-style TSV sources without interpreting entity notation.

    A scalar is usable only if all of its supplied definitions are the same
    single parseable operator-bearing IDS. Self/other atomic definitions stay
    opaque, and conflicts or unparseable definitions are marked uncertain.
    Exact duplicate definitions across lines/files do not create ambiguity.
    """
    if not sources:
        raise ValueError("at least one source is required")
    values: dict[str, set[str]] = defaultdict(set)
    malformed_keys: set[str] = set()
    counts: Counter = Counter()
    source_records = []
    for source_number, spec in enumerate(sources, 1):
        if (not isinstance(spec.sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", spec.sha256)
                or not isinstance(spec.provenance, str) or not spec.provenance.strip()
                or not isinstance(spec.license, str) or not spec.license.strip()):
            raise ValueError("source needs a SHA-256, provenance and license")
        path = Path(spec.path)
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != spec.sha256.lower():
            raise ValueError(f"source SHA-256 mismatch: {path}")
        # A logical identifier avoids exposing filesystem paths in results.
        source_records.append({"path": f"source-{source_number}", "sha256": digest,
                               "provenance": spec.provenance, "license": spec.license})
        for line in data.decode("utf-8").splitlines():
            if not line or line.startswith(";;"):
                continue
            counts["source_rows"] += 1
            fields = line.split("\t")
            code = re.fullmatch(r"(?:U\+([0-9A-Fa-f]{4,6})|U-([0-9A-Fa-f]{8}))", fields[0])
            if not code:
                counts["unkeyed_rows"] += 1
                continue
            number = int(code.group(1) or code.group(2), 16)
            if number > 0x10FFFF or 0xD800 <= number <= 0xDFFF:
                counts["unkeyed_rows"] += 1
                continue
            char = chr(number)
            parsed_char = parse_ids(char)
            if parsed_char.status != "valid" or not isinstance(parsed_char.tree, Leaf):
                counts["unkeyed_rows"] += 1
                continue
            if len(fields) < 3 or fields[1] != char or any(not x for x in fields[2:]):
                counts["malformed_rows"] += 1
                malformed_keys.add(char)
                continue
            values[char].update(fields[2:])
    definitions, opaque = {}, {}
    for char in sorted(set(values) | malformed_keys):
        items = values[char]
        if char in malformed_keys:
            opaque[char] = "malformed"
        elif len(items) != 1:
            opaque[char] = "ambiguous"
        else:
            result = parse_ids(next(iter(items)))
            if result.status != "valid":
                opaque[char] = "unparseable"
            elif isinstance(result.tree, Leaf):
                opaque[char] = "atomic"
            else:
                definitions[char] = result.tree
        counts["definition_" + (opaque.get(char) or "usable")] += 1
    # Group original definitions only: no recursive lookup or family folding.
    grouped: dict[Tree, list[str]] = defaultdict(list)
    for char, definition in definitions.items():
        grouped[normalize(definition)].append(char)
    collisions = sorted((chars for chars in grouped.values() if len(chars) > 1),
                        key=lambda chars: chars[0])
    examples = [{"characters": chars[:8], "character_count": len(chars),
                 "representative_ids": _serialize(definitions[chars[0]])}
                for chars in collisions[:10]]
    metadata = {"mode": "experimental-decomposition-allowance-not-image-correctness",
                "sources": source_records, "counts": dict(sorted(counts.items())),
                "single_definition_collisions": {
                    "class_count": len(collisions),
                    "character_count": sum(len(chars) for chars in collisions),
                    "examples": examples, "example_limit": 10, "characters_per_example_limit": 8,
                    "scope": "Single-level definitions after same-axis normalization; not exhaustive transitive expansion collisions.",
                    "interpretation": "Provisional structural sensitivity; shared IDS does not establish visual identity."}}
    return ExpansionIndex(definitions, opaque, metadata)


class _ExpansionFailure(Exception):
    def __init__(self, status: str, reason: str):
        self.status, self.reason = status, reason
        super().__init__(reason)


def _serialize(tree: Tree) -> str:
    if isinstance(tree, Leaf):
        return tree.component
    return tree.operator + "".join(_serialize(child) for child in tree.children)


def _expand(text: str, index: ExpansionIndex, target: str, max_depth: int,
            max_nodes: int) -> tuple[SideResult, Optional[Tree]]:
    parsed = parse_ids(text)
    if parsed.status != "valid":
        return SideResult("parse_" + parsed.status, (), parsed.reason), None
    trace: list[dict] = []
    nodes = 0

    def visit(tree: Tree, depth: int, path: tuple[int, ...], active: tuple[str, ...], *, root=False) -> Tree:
        nonlocal nodes
        if depth > max_depth:
            raise _ExpansionFailure("depth_limit", f"tree depth exceeds {max_depth}")
        if isinstance(tree, Leaf) and not root:
            component = tree.component
            # A variation selector does not hide the target scalar. Dictionary
            # lookup itself remains exact and never folds variation sequences.
            if component[0] == target:
                raise _ExpansionFailure("target_blocked", f"target component {component} cannot be expanded")
            reason = index.opaque_reasons.get(component)
            if reason and reason != "atomic":
                raise _ExpansionFailure("uncertain", f"{component}: {reason} source definition")
            definition = index.definitions.get(component)
            if definition is not None:
                if component in active:
                    raise _ExpansionFailure("cycle", f"active-path cycle at {component}")
                trace.append({"path": list(path), "component": component, "definition": _serialize(definition)})
                return visit(definition, depth, path, active + (component,))
        nodes += 1
        if nodes > max_nodes:
            raise _ExpansionFailure("node_limit", f"expanded tree exceeds {max_nodes} nodes")
        if isinstance(tree, Leaf):
            return tree
        return Node(tree.operator, tuple(visit(child, depth + 1, path + (i,), active)
                                         for i, child in enumerate(tree.children)))

    try:
        tree = visit(parsed.tree, 0, (), (), root=True)
        return SideResult("ok", tuple(trace)), normalize(tree)
    except _ExpansionFailure as exc:
        return SideResult(exc.status, tuple(trace), exc.reason), None


def compare(prediction: str, reference: str, *, index: ExpansionIndex, target: str,
            max_depth: int = 64, max_nodes: int = 1024,
            family_rules: Optional[Sequence[FamilyRule]] = None) -> Comparison:
    """Compare expanded trees symmetrically; None means indeterminate.

    Root leaves are never dictionary-expanded. Dictionary expansion cannot
    introduce or expand the target character, and a failed expansion cannot
    produce an accepted match. Bounds apply independently to each full tree.
    Trace paths are child indices in the expanding tree at the time of each
    substitution, and include the original exact component and source IDS.
    If family_rules is supplied, family_match separately applies the evaluator's
    direct, contextual rules to the expanded normalized trees. It is None when
    disabled or either expansion is indeterminate; no rule closure is applied.
    """
    if not isinstance(target, str) or len(target) != 1 or 0xD800 <= ord(target) <= 0xDFFF:
        raise ValueError("target must be one Unicode scalar")
    if type(max_depth) is not int or not 0 <= max_depth <= 128:
        raise ValueError("max_depth must be an integer from 0 to 128")
    if type(max_nodes) is not int or not 1 <= max_nodes <= 100000:
        raise ValueError("max_nodes must be an integer from 1 to 100000")
    pred, p_tree = _expand(prediction, index, target, max_depth, max_nodes)
    ref, r_tree = _expand(reference, index, target, max_depth, max_nodes)
    scorable = p_tree is not None and r_tree is not None
    match = p_tree == r_tree if scorable else None
    family = _family_match(p_tree, r_tree, family_rules) if scorable and family_rules is not None else None
    return Comparison(match, pred, ref, family)


@dataclass(frozen=True)
class SelectiveComparison:
    """A witnessed match, a complete no-match, or an indeterminate search."""
    match: Optional[bool]
    status: str
    states_visited: int
    prediction_trace: tuple[dict, ...]
    reference_trace: tuple[dict, ...]
    indeterminate_reasons: tuple[str, ...]


@dataclass(frozen=True)
class _TaggedLeaf:
    component: str
    ancestry: tuple[str, ...] = ()
    alias_origin: Optional[str] = None
    alias_history: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class _TaggedNode:
    operator: str
    children: tuple  # _TaggedLeaf | _TaggedNode


def _tag(tree: Tree, ancestry: tuple[str, ...] = (), alias_history: tuple[tuple[str, str], ...] = ()):
    if isinstance(tree, Leaf):
        return _TaggedLeaf(tree.component, ancestry, alias_history=alias_history)
    return _TaggedNode(tree.operator, tuple(_tag(child, ancestry, alias_history) for child in tree.children))


def _untag(tree) -> Tree:
    if isinstance(tree, _TaggedLeaf):
        return Leaf(tree.component)
    return Node(tree.operator, tuple(_untag(child) for child in tree.children))


def _normalize_tagged(tree):
    """Same-axis normalization while retaining per-leaf alias provenance."""
    if isinstance(tree, _TaggedLeaf):
        return tree
    axis = "H" if tree.operator in "⿰⿲" else "V" if tree.operator in "⿱⿳" else None
    children = tuple(_normalize_tagged(child) for child in tree.children)
    if axis:
        flat = []
        for child in children:
            if isinstance(child, _TaggedNode) and child.operator == axis:
                flat.extend(child.children)
            else:
                flat.append(child)
        return _TaggedNode(axis, tuple(flat))
    return _TaggedNode(tree.operator, children)


def _tagged_matches(a, b, rules, path=()):
    """Match directly, without applying another alias to an aliased leaf."""
    if isinstance(a, _TaggedLeaf) and isinstance(b, _TaggedLeaf):
        # Expanding an alias resets the local rewrite budget, but its provenance
        # remains attached to every descendant even after axis flattening.
        history_a = a.alias_history + (((a.alias_origin, a.component),) if a.alias_origin else ())
        history_b = b.alias_history + (((b.alias_origin, b.component),) if b.alias_origin else ())
        if any(dest_a == dest_b and source_a != source_b
               for source_a, dest_a in history_a for source_b, dest_b in history_b):
            return False
        if a.component == b.component:
            if a.alias_origin and b.alias_origin and a.alias_origin != b.alias_origin:
                # Converging two independent rewrites cannot create A~B~C.
                return _family_match(Leaf(a.alias_origin), Leaf(b.alias_origin), rules, path)
            return True
        if a.alias_origin or b.alias_origin:
            return False
        return _family_match(Leaf(a.component), Leaf(b.component), rules, path)
    if not isinstance(a, _TaggedNode) or not isinstance(b, _TaggedNode):
        return False
    return (a.operator == b.operator and len(a.children) == len(b.children)
            and all(_tagged_matches(left, right, rules, path + ((a.operator, i),))
                    for i, (left, right) in enumerate(zip(a.children, b.children))))


def _replace_tagged(tree, path: tuple[int, ...], replacement):
    if not path:
        return replacement
    child_index = path[0]
    children = list(tree.children)
    children[child_index] = _replace_tagged(children[child_index], path[1:], replacement)
    return _TaggedNode(tree.operator, tuple(children))


def _selective_inspect(tree, index: ExpansionIndex, target: str, max_depth: int, max_nodes: int):
    """Return expandable paths, aliasable leaves, and unsafe reasons."""
    paths, leaves, reasons = [], [], set()
    node_count = 0

    def visit(node, path):
        nonlocal node_count
        node_count += 1
        if node_count > max_nodes:
            reasons.add("node_limit")
            return
        if len(path) > max_depth:
            reasons.add("depth_limit")
            return
        if isinstance(node, _TaggedNode):
            for i, child in enumerate(node.children):
                if node_count > max_nodes:
                    break
                visit(child, path + (i,))
            return
        if not path:  # A root leaf is never dictionary-expanded.
            return
        component = node.component
        if component[0] == target:
            reasons.add("target_blocked")
            return
        reason = index.opaque_reasons.get(component)
        if reason and reason != "atomic":
            reasons.add("uncertain_definition")
            return
        if component in index.definitions:
            if component in node.ancestry:
                reasons.add("cycle")
            else:
                paths.append((path, node))
        if node.alias_origin is None:
            leaves.append((path, node))

    visit(tree, ())
    return paths, leaves, reasons


def compare_selective(prediction: str, reference: str, *, index: ExpansionIndex,
                      target: str, family_rules: Optional[Sequence[FamilyRule]] = None,
                      max_depth: int = 64, max_nodes: int = 1024,
                      max_states: int = 256) -> SelectiveComparison:
    """Search selective non-root expansions for a directly witnessed match.

    This experimental sensitivity diagnostic is distinct from ``compare``'s
    exhaustive expansion and does not establish visual identity. At each state,
    opaque versus expanded components may differ on either side. A contextual
    direct alias may be applied once per leaf before expansion, with the alias
    budget reset for genuinely new descendants. Terminal matches retain alias
    provenance and prohibit transitive alias chains. Equal-depth BFS, canonical initial orientation and
    left-to-right paths make results deterministic and symmetric under swapping.
    Root leaves stay opaque. Unsafe states cannot witness matches. A witnessed
    match is true; absent a witness, any ambiguity, cycle, target block or
    resource bound makes the result indeterminate. A normalized candidate
    rejected solely by alias-history constraints is likewise indeterminate.
    Unknown dictionary entries
    stay opaque, and a completely explored safe search without a witness is false.

    ``max_states`` bounds distinct pair states, including alias states and the
    initial state. Traces record each expansion (component, definition) and
    alias (component, alias) with the child path in witnessed order.
    """
    if not isinstance(target, str) or len(target) != 1 or 0xD800 <= ord(target) <= 0xDFFF:
        raise ValueError("target must be one Unicode scalar")
    if type(max_depth) is not int or not 0 <= max_depth <= 128:
        raise ValueError("max_depth must be an integer from 0 to 128")
    if type(max_nodes) is not int or not 1 <= max_nodes <= 100000:
        raise ValueError("max_nodes must be an integer from 1 to 100000")
    if type(max_states) is not int or not 1 <= max_states <= 10000:
        raise ValueError("max_states must be an integer from 1 to 10000")
    first, second = parse_ids(prediction), parse_ids(reference)
    reasons = set()
    if first.status != "valid":
        reasons.add("prediction_parse_" + first.status)
    if second.status != "valid":
        reasons.add("reference_parse_" + second.status)
    if reasons:
        return SelectiveComparison(None, "indeterminate", 0, (), (), tuple(sorted(reasons)))
    # Fix the search orientation independently of which side is called prediction.
    swapped = prediction > reference
    left, right = (second.tree, first.tree) if swapped else (first.tree, second.tree)
    initial = (_tag(left), _tag(right))
    queue = deque([(initial[0], initial[1], (), ())])
    seen = {initial}
    visited = 0
    while queue:
        a, b, trace_a, trace_b = queue.popleft()
        visited += 1
        choices_a, leaves_a, bad_a = _selective_inspect(a, index, target, max_depth, max_nodes)
        choices_b, leaves_b, bad_b = _selective_inspect(b, index, target, max_depth, max_nodes)
        if bad_a or bad_b:
            reasons.update(bad_a | bad_b)
            continue
        x, y = normalize(_untag(a)), normalize(_untag(b))
        equal = (x == y if family_rules is None else
                 _tagged_matches(_normalize_tagged(a), _normalize_tagged(b), family_rules))
        if equal:
            pred_trace, ref_trace = (trace_b, trace_a) if swapped else (trace_a, trace_b)
            return SelectiveComparison(True, "matched", visited, pred_trace, ref_trace, tuple(sorted(reasons)))
        if family_rules is not None and _family_match(x, y, family_rules):
            # Trees match when provenance constraints are ignored. Axis
            # flattening can make independent alias spans overlap, so the
            # history check alone cannot prove that no safe witness exists.
            reasons.add("alias_history_ambiguous")

        def enqueue(side, new_tree, step):
            new_a, new_b = (new_tree, b) if side == 0 else (a, new_tree)
            key = (new_a, new_b)
            if key in seen:
                return
            if len(seen) >= max_states:
                reasons.add("search_limit")
                return
            seen.add(key)
            next_a, next_b = ((trace_a + (step,), trace_b) if side == 0
                              else (trace_a, trace_b + (step,)))
            queue.append((new_a, new_b, next_a, next_b))

        for side, choices in ((0, choices_a), (1, choices_b)):
            for path, leaf in choices:
                definition = index.definitions[leaf.component]
                history = leaf.alias_history + (((leaf.alias_origin, leaf.component),) if leaf.alias_origin else ())
                replacement = _tag(definition, leaf.ancestry + (leaf.component,), history)
                new_tree = _replace_tagged(a if side == 0 else b, path, replacement)
                enqueue(side, new_tree, {"path": list(path), "component": leaf.component,
                                         "definition": _serialize(definition)})
        if family_rules:
            for side, leaves in ((0, leaves_a), (1, leaves_b)):
                tree = a if side == 0 else b
                original = x if side == 0 else y
                for path, leaf in leaves:
                    aliases = sorted({member for rule in family_rules if leaf.component in rule.components
                                      for member in rule.components if member != leaf.component})
                    for alias in aliases:
                        replacement = _TaggedLeaf(alias, leaf.ancestry, leaf.component, leaf.alias_history)
                        new_tree = _replace_tagged(tree, path, replacement)
                        # Verify the exact normalized context; no implied aliases.
                        if not _family_match(original, normalize(_untag(new_tree)), family_rules):
                            continue
                        parsed_alias = parse_ids(alias)
                        if parsed_alias.status != "valid" or not isinstance(parsed_alias.tree, Leaf):
                            reasons.add("unsupported_alias")
                            continue
                        if alias[0] == target:
                            reasons.add("target_blocked")
                            continue
                        enqueue(side, new_tree, {"path": list(path), "component": leaf.component,
                                                 "alias": alias})
    if reasons:
        return SelectiveComparison(None, "indeterminate", visited, (), (), tuple(sorted(reasons)))
    return SelectiveComparison(False, "no_match", visited, (), (), ())
