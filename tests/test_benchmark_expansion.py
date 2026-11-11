from dataclasses import asdict
import hashlib

import pytest

from benchmark.expansion import SourceSpec, compare, compare_selective, load_sources
from benchmark.ids_evaluator import FamilyRule


def source(tmp_path, text, name="ids.tsv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return SourceSpec(path, hashlib.sha256(path.read_bytes()).hexdigest(),
                      "test fixture / pinned revision", "test-only")


def index(tmp_path, text):
    return load_sources([source(tmp_path, text)])


def test_nested_expansion_is_symmetric_and_traced(tmp_path):
    idx = index(tmp_path, ";; header\nU+6797\t林\t⿰木木\n")
    a, b = "⿰氵林", "⿰氵⿰木木"
    result = compare(a, b, index=idx, target="淋")
    assert result.match is True
    assert result.prediction.status == result.reference.status == "ok"
    assert result.prediction.trace == ({"path": [1], "component": "林", "definition": "⿰木木"},)
    reverse = compare(b, a, index=idx, target="淋")
    assert reverse.match is True
    assert result.prediction == reverse.reference and result.reference == reverse.prediction
    assert asdict(result)["prediction"]["trace"][0]["component"] == "林"
    assert idx.metadata["counts"]["definition_usable"] == 1
    assert idx.metadata["sources"][0]["sha256"] and idx.metadata["sources"][0]["license"] == "test-only"


def test_definition_collisions_and_portable_source_ids(tmp_path):
    idx = index(tmp_path, "U+7532\t甲\t⿰⿰木日日\nU+4E59\t乙\t⿲木日日\n"
                          "U+4E19\t丙\t⿱木日\nU+4E01\t丁\t⿱木日\n")
    collision = idx.metadata["single_definition_collisions"]
    assert collision["class_count"] == 2
    assert collision["character_count"] == 4
    assert any(set(item["characters"]) == {"甲", "乙"} for item in collision["examples"])
    assert any(set(item["characters"]) == {"丙", "丁"} for item in collision["examples"])
    assert "not exhaustive transitive" in collision["scope"]
    assert "does not establish visual identity" in collision["interpretation"]
    assert idx.metadata["sources"][0]["path"] == "source-1"
    assert str(tmp_path) not in str(idx.metadata)


def test_collision_examples_have_explicit_bounds(tmp_path):
    rows = []
    for group in range(12):
        for member in range(10):
            char = chr(0x4E00 + group * 10 + member)
            component = chr(0x4F00 + group)
            rows.append(f"U+{ord(char):04X}\t{char}\t⿰木{component}\n")
    idx = index(tmp_path, "".join(rows))
    collision = idx.metadata["single_definition_collisions"]
    assert collision["class_count"] == 12 and collision["character_count"] == 120
    assert len(collision["examples"]) == collision["example_limit"] == 10
    assert all(len(e["characters"]) == collision["characters_per_example_limit"] == 8
               and e["character_count"] == 10 for e in collision["examples"])


def test_expansion_plus_explicit_contextual_family_rules(tmp_path):
    idx = index(tmp_path, "U+8ECC\t軌\t⿰金九\n")
    left = (("⿷", 1), ("H", 0))
    rule = FamilyRule(frozenset(("金", "釒")), frozenset((left,)))
    prediction, reference = "⿷匚⿰釒九", "⿷匚軌"
    strict = compare(prediction, reference, index=idx, target="医")
    assert strict.match is False and strict.family_match is None
    assert compare(prediction, reference, index=idx, target="医", family_rules=[]).family_match is False
    combined = compare(prediction, reference, index=idx, target="医", family_rules=[rule])
    assert combined.match is False and combined.family_match is True
    assert combined.reference.trace[0]["component"] == "軌"
    assert compare(reference, prediction, index=idx, target="医", family_rules=[rule]).family_match is True
    wrong_context = FamilyRule(frozenset(("金", "釒")), frozenset(((("H", 0),),)))
    assert compare(prediction, reference, index=idx, target="医", family_rules=[wrong_context]).family_match is False
    # Direct pair rules do not close transitively via 銅.
    first = FamilyRule(frozenset(("釒", "銅")), frozenset((left,)))
    second = FamilyRule(frozenset(("銅", "金")), frozenset((left,)))
    assert compare(prediction, reference, index=idx, target="医", family_rules=[first, second]).family_match is False
    root = compare("軌", "⿰釒九", index=idx, target="軌", family_rules=[rule])
    assert root.match is False and root.family_match is False
    blocked = compare("⿷匚軌", reference, index=idx, target="軌", family_rules=[rule])
    assert blocked.match is blocked.family_match is None
    assert blocked.prediction.status == "target_blocked"


def test_family_matching_refuses_uncertain_expansions(tmp_path):
    idx = index(tmp_path, "U+8ECC\t軌\t⿰金九\t⿱金九\n")
    rule = FamilyRule(frozenset(("金", "釒")), contexts=frozenset((("H", 0),)))
    result = compare("⿷匚⿰釒九", "⿷匚軌", index=idx, target="医", family_rules=[rule])
    assert result.match is result.family_match is None
    assert result.reference.status == "uncertain"


def test_selective_expansion_preserves_opaque_alias(tmp_path):
    idx = index(tmp_path, "U+6C35\t氵\t⿱一二\nU+6728\t木\t⿱日月\n")
    rule = FamilyRule(frozenset(("氵", "水")), contexts=frozenset((("H", 0),)))
    pred, ref = "⿰氵木", "⿰水⿱日月"
    assert compare(pred, ref, index=idx, target="林", family_rules=[rule]).family_match is False
    out = compare_selective(pred, ref, index=idx, target="林", family_rules=[rule])
    assert out.match is True and out.status == "matched"
    assert [x["component"] for x in out.prediction_trace] == ["木"]
    assert out.reference_trace == ()
    reverse = compare_selective(ref, pred, index=idx, target="林", family_rules=[rule])
    assert reverse.match is True and reverse.states_visited == out.states_visited
    assert reverse.reference_trace == out.prediction_trace and reverse.prediction_trace == out.reference_trace
    assert compare_selective(pred, ref, index=idx, target="林").match is False
    wrong = FamilyRule(frozenset(("氵", "水")), contexts=frozenset((("H", 1),)))
    assert compare_selective(pred, ref, index=idx, target="林", family_rules=[wrong]).match is False
    assert compare_selective(pred, ref, index=idx, target="林", family_rules=[rule]) == out


def test_selective_alias_before_expansion_and_symmetry(tmp_path):
    idx = index(tmp_path, "U+6C34\t水\t⿱日月\n")
    rule = FamilyRule(frozenset(("氵", "水")), contexts=frozenset((("H", 0),)))
    pred, ref = "⿰氵火", "⿰⿱日月火"
    out = compare_selective(pred, ref, index=idx, target="林", family_rules=[rule])
    assert out.match is True
    assert out.prediction_trace == ({"path": [0], "component": "氵", "alias": "水"},
                                    {"path": [0], "component": "水", "definition": "⿱日月"})
    reverse = compare_selective(ref, pred, index=idx, target="林", family_rules=[rule])
    assert reverse.match is True and reverse.reference_trace == out.prediction_trace
    assert reverse.states_visited == out.states_visited
    assert compare_selective(pred, ref, index=idx, target="林").match is False
    truncated = compare_selective(pred, ref, index=idx, target="林", family_rules=[rule], max_states=1)
    assert truncated.match is None and "search_limit" in truncated.indeterminate_reasons
    depth = compare_selective(pred, ref, index=idx, target="林", family_rules=[rule], max_depth=1)
    assert depth.match is None and "depth_limit" in depth.indeterminate_reasons
    nodes = compare_selective(pred, ref, index=idx, target="林", family_rules=[rule], max_nodes=3)
    assert nodes.match is None and "node_limit" in nodes.indeterminate_reasons
    wrong = FamilyRule(frozenset(("氵", "水")), contexts=frozenset((("H", 1),)))
    assert compare_selective(pred, ref, index=idx, target="林", family_rules=[wrong]).match is False
    blocked = compare_selective(pred, ref, index=idx, target="水", family_rules=[rule])
    assert blocked.match is None and "target_blocked" in blocked.indeterminate_reasons


def test_selective_aliases_do_not_chain_or_converge(tmp_path):
    idx = index(tmp_path, "U+6C34\t水\t⿱日月\n")
    rules = [FamilyRule(frozenset(("氵", "川")), contexts=frozenset((("H", 0),))),
             FamilyRule(frozenset(("川", "水")), contexts=frozenset((("H", 0),)))]
    for pred, ref in (("⿰氵火", "⿰水火"), ("⿰水火", "⿰氵火")):
        result = compare_selective(pred, ref, index=idx, target="林", family_rules=rules)
        assert result.match is None and result.status == "indeterminate"
        assert "alias_history_ambiguous" in result.indeterminate_reasons
    # Reaching the expanded 水 would require two aliases on the same leaf;
    # no normalized matching candidate is reached.
    result = compare_selective("⿰氵火", "⿰⿱日月火", index=idx, target="林", family_rules=rules)
    assert result.match is False and result.status == "no_match"


def test_selective_overlapping_history_is_indeterminate(tmp_path):
    idx = index(tmp_path, "U+6C34\t水\t⿰木木\n")
    rules = [FamilyRule(frozenset(("甲", "水")), contexts=frozenset((("H", 0),))),
             FamilyRule(frozenset(("乙", "水")), contexts=frozenset((("H", 1),)))]
    a, b = "⿰甲木", "⿰木乙"
    forward = compare_selective(a, b, index=idx, target="林", family_rules=rules)
    reverse = compare_selective(b, a, index=idx, target="林", family_rules=rules)
    assert forward.match is None and forward.status == "indeterminate"
    assert "alias_history_ambiguous" in forward.indeterminate_reasons
    assert reverse.match is None and reverse.indeterminate_reasons == forward.indeterminate_reasons
    assert reverse.states_visited == forward.states_visited


def test_selective_rejects_transitive_convergence_after_expansion(tmp_path):
    idx = index(tmp_path, "U+6C34\t水\t⿱一二\n")
    rules = [FamilyRule(frozenset((component, "水")), contexts=frozenset((("H", 0),)))
             for component in ("氵", "川")]
    pred, ref = "⿰氵火", "⿰川火"
    out = compare_selective(pred, ref, index=idx, target="林", family_rules=rules, max_states=20)
    reverse = compare_selective(ref, pred, index=idx, target="林", family_rules=rules, max_states=20)
    assert out.match is None and out.status == "indeterminate"
    assert "alias_history_ambiguous" in out.indeterminate_reasons
    assert reverse.match is None and reverse.states_visited == out.states_visited
    # Direct alias followed by expansion is still allowed.
    direct = compare_selective(pred, "⿰⿱一二火", index=idx, target="林", family_rules=rules)
    assert direct.match is True
    assert direct.prediction_trace == ({"path": [0], "component": "氵", "alias": "水"},
                                       {"path": [0], "component": "水", "definition": "⿱一二"})


@pytest.mark.parametrize("definition", ["⿰一二", "⿱甲二"])
def test_alias_provenance_survives_flattening_and_nested_expansion(tmp_path, definition):
    idx = index(tmp_path, f"U+6C34\t水\t{definition}\nU+7532\t甲\t⿱一日\n")
    rules = [FamilyRule(frozenset((component, "水")), contexts=frozenset((("H", 0),)))
             for component in ("氵", "川")]
    a, b = "⿰氵火", "⿰川火"
    forward = compare_selective(a, b, index=idx, target="林", family_rules=rules, max_states=256)
    reverse = compare_selective(b, a, index=idx, target="林", family_rules=rules, max_states=256)
    assert forward.match is None and reverse.match is None
    assert "alias_history_ambiguous" in forward.indeterminate_reasons
    assert forward.states_visited == reverse.states_visited
    direct = compare_selective(a, "⿰" + definition + "火", index=idx, target="林", family_rules=rules)
    assert direct.match is True


def test_selective_alias_cycle_is_indeterminate(tmp_path):
    idx = index(tmp_path, "U+4E59\t乙\t⿰甲木\n")
    rule = FamilyRule(frozenset(("甲", "乙")), contexts=frozenset((("H", 0),)))
    result = compare_selective("⿰甲火", "⿰山火", index=idx, target="明", family_rules=[rule])
    assert result.match is None and "cycle" in result.indeterminate_reasons


def test_selective_expands_both_sides_without_alias_closure(tmp_path):
    idx = index(tmp_path, "U+7532\t甲\t⿱一二\nU+4E59\t乙\t⿱日月\n")
    out = compare_selective("⿰甲日", "⿰⿱一二乙", index=idx, target="林")
    assert out.match is False  # Expanding 乙 adds structure rather than matching 日.
    out = compare_selective("⿰甲⿱日月", "⿰⿱一二乙", index=idx, target="林")
    assert out.match is True
    assert [x["component"] for x in out.prediction_trace] == ["甲"]
    assert [x["component"] for x in out.reference_trace] == ["乙"]
    left = (("H", 0),)
    rules = [FamilyRule(frozenset(("氵", "川")), frozenset((left,))),
             FamilyRule(frozenset(("川", "水")), frozenset((left,)))]
    uncertain = compare_selective("⿰氵日", "⿰水日", index=idx, target="林", family_rules=rules)
    assert uncertain.match is None and "alias_history_ambiguous" in uncertain.indeterminate_reasons


def test_selective_cycle_unknown_ambiguity_and_bounds(tmp_path):
    idx = index(tmp_path, "U+7532\t甲\t⿰乙木\nU+4E59\t乙\t⿱甲日\n"
                          "U+6797\t林\t⿰木木\t⿱木木\n")
    cycle = compare_selective("⿰甲火", "⿰山火", index=idx, target="明")
    assert cycle.match is None and "cycle" in cycle.indeterminate_reasons
    ambiguous = compare_selective("⿰林火", "⿰林火", index=idx, target="明")
    assert ambiguous.match is None and "uncertain_definition" in ambiguous.indeterminate_reasons
    unknown = compare_selective("⿰土火", "⿰山火", index=idx, target="明")
    assert unknown.match is False and unknown.status == "no_match"
    limited = compare_selective("⿰甲火", "⿰山火", index=idx, target="明", max_states=1)
    assert limited.match is None and "search_limit" in limited.indeterminate_reasons
    reverse = compare_selective("⿰山火", "⿰甲火", index=idx, target="明", max_states=1)
    assert reverse.match is None and reverse.indeterminate_reasons == limited.indeterminate_reasons
    assert reverse.states_visited == limited.states_visited
    depth = compare_selective("⿰甲火", "⿰山火", index=idx, target="明", max_depth=1)
    assert depth.match is None and "depth_limit" in depth.indeterminate_reasons
    nodes = compare_selective("⿰甲火", "⿰山火", index=idx, target="明", max_nodes=2)
    assert nodes.match is None and "node_limit" in nodes.indeterminate_reasons
    with pytest.raises(ValueError, match="max_states"):
        compare_selective("木", "日", index=idx, target="明", max_states=0)
    invalid = compare_selective("?", "木", index=idx, target="明")
    assert invalid.match is None and "prediction_parse_unsupported" in invalid.indeterminate_reasons


def test_selective_exact_state_cap_without_truncation(tmp_path):
    idx = index(tmp_path, "U+7532\t甲\t⿰木木\n")
    result = compare_selective("⿱甲火", "⿱山火", index=idx, target="明", max_states=2)
    assert result.match is False and result.states_visited == 2
    assert result.indeterminate_reasons == ()
    truncated = compare_selective("⿱甲火", "⿱山火", index=idx, target="明", max_states=1)
    assert truncated.match is None and "search_limit" in truncated.indeterminate_reasons


def test_selective_root_and_target_guards(tmp_path):
    idx = index(tmp_path, "U+660E\t明\t⿰日月\nU+7532\t甲\t⿰明木\n")
    assert compare_selective("明", "⿰日月", index=idx, target="明").match is False
    assert compare_selective("明", "明", index=idx, target="明").match is True
    blocked = compare_selective("⿰甲火", "⿰水火", index=idx, target="明")
    assert blocked.match is None and "target_blocked" in blocked.indeterminate_reasons
    literal = compare_selective("⿰明木", "⿰明木", index=idx, target="明")
    assert literal.match is None and "target_blocked" in literal.indeterminate_reasons


def test_whole_root_leaf_never_expands(tmp_path):
    idx = index(tmp_path, "U+660E\t明\t⿰日月\n")
    assert compare("明", "⿰日月", index=idx, target="明").match is False
    assert compare("明", "明", index=idx, target="明").match is True
    blocked = compare("⿰明木", "⿰⿰日月木", index=idx, target="明")
    assert blocked.match is None and blocked.prediction.status == "target_blocked"
    assert blocked.prediction.trace == ()
    # A selector does not conceal the target scalar inside a component.
    selected = compare("⿰明\ufe0f木", "⿰明\ufe0f木", index=idx, target="明")
    assert selected.match is None and selected.prediction.status == "target_blocked"


def test_target_cannot_be_introduced_at_any_depth(tmp_path):
    idx = index(tmp_path, "U+7532\t甲\t⿰乙木\nU+4E59\t乙\t⿰明日\n")
    result = compare("⿱甲火", "⿱⿰⿰明日木火", index=idx, target="明")
    assert result.match is None
    assert result.prediction.status == "target_blocked"
    assert [entry["component"] for entry in result.prediction.trace] == ["甲", "乙"]


def test_ambiguous_unparseable_atomic_and_duplicates(tmp_path):
    one = source(tmp_path, "U+6797\t林\t⿰木木\nU+7532\t甲\t⿰木日\t⿱木日\n"
                          "U+4E59\t乙\t⿰木&missing;\nU+4E00\t一\t一\n")
    two = source(tmp_path, "U+6797\t林\t⿰木木\n", "second.tsv")
    idx = load_sources([one, two])
    assert idx.metadata["counts"]["definition_ambiguous"] == 1
    assert idx.metadata["counts"]["definition_unparseable"] == 1
    assert idx.metadata["counts"]["definition_atomic"] == 1
    assert idx.metadata["counts"]["definition_usable"] == 1
    for char in ("甲", "乙"):
        result = compare("⿰" + char + "木", "⿰" + char + "木", index=idx, target="明")
        assert result.match is None and result.prediction.status == "uncertain"
    assert compare("⿰一木", "⿰一木", index=idx, target="明").match is True
    # Variation sequences are exact, not base-character dictionary keys.
    assert compare("⿰林\ufe0f木", "⿰⿰木木木", index=idx, target="明").match is False


def test_chise_supplementary_keys_and_scalar_validation(tmp_path):
    idx = index(tmp_path, "U-00020002\t𠀂\t⿱一乙\n"
                          "U+20002\t𠀂\t⿱一乙\n"
                          "U-00020004\t𠀅\t⿱一丿\n"
                          "U-00110000\t𠀀\t⿱一丿\n"
                          "U-0000D800\t𠀀\t⿱一丿\n"
                          "U-0020002\t𠀂\t⿱一乙\n")
    assert idx.metadata["counts"]["definition_usable"] == 1
    assert idx.metadata["counts"]["malformed_rows"] == 1
    assert idx.metadata["counts"]["unkeyed_rows"] == 3
    assert idx.opaque_reasons["𠀄"] == "malformed"
    assert "𠀅" not in idx.definitions
    out = compare("⿰木𠀂", "⿰木⿱一乙", index=idx, target="明")
    assert out.match is True
    assert out.prediction.trace[0]["component"] == "𠀂"
    bad = compare("⿰木𠀄", "⿰木𠀄", index=idx, target="明")
    assert bad.match is None and bad.prediction.status == "uncertain"


def test_conflicts_across_sources_and_malformed_rows(tmp_path):
    first = source(tmp_path, "U+6797\t林\t⿰木木\nU+7532\t乙\t⿰木木\n")
    other = source(tmp_path, "U+6797\t林\t⿱木木\n", "other.tsv")
    idx = load_sources([first, other])
    assert idx.opaque_reasons["林"] == "ambiguous"
    assert idx.opaque_reasons["甲"] == "malformed"
    assert compare("⿰林木", "⿰林木", index=idx, target="明").match is None


def test_cycle_and_resource_limits_never_accept(tmp_path):
    idx = index(tmp_path, "U+7532\t甲\t⿰乙木\nU+4E59\t乙\t⿱甲日\n")
    out = compare("⿰甲火", "⿰甲火", index=idx, target="明")
    assert out.match is None and out.prediction.status == out.reference.status == "cycle"
    plain = index(tmp_path, "U+6797\t林\t⿰木木\n")
    depth = compare("⿰林火", "⿰林火", index=plain, target="明", max_depth=1)
    assert depth.match is None and depth.prediction.status == "depth_limit"
    nodes = compare("⿰林火", "⿰林火", index=plain, target="明", max_nodes=3)
    assert nodes.match is None and nodes.prediction.status == "node_limit"
    with pytest.raises(ValueError):
        compare("木", "木", index=plain, target="明", max_depth=129)


def test_input_parse_and_source_pinning(tmp_path):
    spec = source(tmp_path, "U+6797\t林\t⿰木木\n")
    idx = load_sources([spec])
    invalid = compare("?", "林", index=idx, target="明")
    assert invalid.match is None and invalid.prediction.status == "parse_unsupported"
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_sources([SourceSpec(spec.path, "0" * 64, "test", "test")])
    with pytest.raises(ValueError, match="provenance"):
        load_sources([SourceSpec(spec.path, spec.sha256, "", "test")])
    with pytest.raises(ValueError, match="target"):
        compare("木", "木", index=idx, target="明日")
