"""Unit tests for the benchmark IDS evaluator."""
import unittest
from unittest.mock import patch

from benchmark.ids_evaluator import ARITY, FamilyRule, Leaf, Node, evaluate, normalize, parse_ids


class ParserTests(unittest.TestCase):
    def test_all_operators_and_arities(self):
        for operator, arity in ARITY.items():
            with self.subTest(operator=operator):
                result = parse_ids(operator + "木" * arity)
                self.assertEqual(result.status, "valid")
                self.assertEqual(result.tree, Node(operator, (Leaf("木"),) * arity))
                self.assertEqual(parse_ids(operator + "木" * (arity - 1)).status, "invalid")
                self.assertEqual(parse_ids(operator + "木" * (arity + 1)).status, "invalid")

    def test_variation_sequences_and_supplementary(self):
        for component in ("𠀀", "\U0002ebf0", "\u31e4", "\u31e5", "木\ufe0f", "𠀀\U000e0100"):
            self.assertEqual(parse_ids(component).tree, Leaf(component))
        for text in ("\ufe0f", "⿰\U000e0100木", "木\ufe0f\ufe0e", "⿰\ufe0f木日"):
            self.assertEqual(parse_ids(text).status, "invalid")
        self.assertFalse(evaluate("木\ufe0f", ["木"]).structural_match)

    def test_invalid_and_unsupported(self):
        for text in ("", "⿰木", "⿰木日月", "abc", "⿰木!", "⿰木 日", "\n", "\u2e9a", "\U0002ee5f"):
            self.assertEqual(parse_ids(text).status, "invalid", text)
        for text in ("?", "⿰木？", "⿻[:-1]〢日", "⿻𬺰#(T)", "⿰木&foo;", "⿰木\ue000"):
            self.assertEqual(parse_ids(text).status, "unsupported", text)
        self.assertEqual(parse_ids("〾⿰爾面").status, "valid")
        self.assertEqual(parse_ids("〾⿱⿰氵𠙉皿").status, "valid")

    def test_unicode_17_assignments_ignore_runtime_ucd(self):
        assigned = ("\U0002b739", "\u31e4", "\U0002ebf0", "\U000323b0", "\U00033479")
        unassigned = ("\u2e9a", "\u2ef4", "\u31e6", "\ufa6e", "\U0002ebe1",
                      "\U0002ee5e", "\U0003134b", "\U0003347a")
        for category in ("Cn", "Lo"):
            with patch("unicodedata.category", return_value=category):
                for char in assigned:
                    self.assertEqual(parse_ids(char).status, "valid", f"U+{ord(char):04X}")
                for char in unassigned:
                    self.assertEqual(parse_ids(char).status, "invalid", f"U+{ord(char):04X}")

    def test_out_of_scope_components_do_not_mask_invalid_structure(self):
        glyphstudio = "⿰口⿳⺈⿰匚コ⿱比兔"
        for category in ("Cn", "Lo"):
            with patch("unicodedata.category", return_value=category):
                for text in (glyphstudio, "コ", "⿰木あ", "⿰木ㄅ", "⿰木😀", "コ\ufe0f", "\U0001e6c0"):
                    result = parse_ids(text)
                    self.assertEqual(result.status, "unsupported", text)
                    self.assertIsNone(result.tree)
                for text in ("⿰コ", "⿰コ木日", "⿰コa", "⿰コ!", "コ\ufe0f\ufe0f"):
                    self.assertEqual(parse_ids(text).status, "invalid", text)
        score = evaluate(glyphstudio, [glyphstudio])
        self.assertIsNone(score.structural_match)
        self.assertEqual(score.prediction_status, "unsupported")

    def test_unknown_private_use_and_extended_are_distinct(self):
        for text in ("?", "？"):
            result = parse_ids(text)
            self.assertEqual((result.status, result.reason), ("unsupported", "unknown component placeholder"))
        for char in ("\ue000", "\uf8ff", "\U000f0000", "\U000ffffd", "\U00100000", "\U0010fffd"):
            result = parse_ids("⿰木" + char)
            self.assertEqual((result.status, result.reason), ("unsupported", "private-use component"))
        for text in ("⿻[:-1]〢日", "⿻𬺰#(T)", "&CDP-1234;"):
            result = parse_ids(text)
            self.assertEqual((result.status, result.reason), ("unsupported", "extended syntax"))
        for char in ("\U000ffffe", "\U0010ffff"):
            self.assertEqual(parse_ids(char).status, "invalid")

    def test_unknown_leaves_obey_operand_grammar(self):
        for char in ("?", "？", "\ue000", "\U000f0000", "\U00100000"):
            for text in (char, "⿰" + char + "木", "⿾" + char):
                with self.subTest(text=text):
                    result = parse_ids(text)
                    self.assertEqual(result.status, "unsupported")
                    self.assertIsNone(result.tree)
            for text in ("⿰" + char, "⿰" + char + "木木", char + "木",
                         "⿲木" + char, "⿰" + char + "!"):
                with self.subTest(text=text):
                    self.assertEqual(parse_ids(text).status, "invalid")
        self.assertEqual(parse_ids("⿰?木木").status, "invalid")
        self.assertEqual(parse_ids("⿰?").status, "invalid")
        for text in ("⿰[?]", "⿰木[:-1]", "⿻#(T)"):
            self.assertEqual(parse_ids(text).status, "unsupported")
        self.assertEqual(evaluate("⿰?", ["木"]).prediction_status, "invalid")
        self.assertIsNone(evaluate("⿰?", ["木"]).structural_match)

    def test_bounds(self):
        self.assertEqual(parse_ids("木" * 513).status, "invalid")
        self.assertEqual(parse_ids("⿾" * 65 + "木").status, "invalid")
        self.assertEqual(parse_ids("⿾" * 64 + "木").status, "valid")


class EvaluationTests(unittest.TestCase):
    def test_axis_flattening_and_arity(self):
        for a, b in (("⿰⿰木日月", "⿲木日月"), ("⿱木⿱日月", "⿳木日月"),
                     ("⿲⿰木日月火", "⿰木⿲日月火")):
            with self.subTest(a=a, b=b):
                self.assertEqual(normalize(parse_ids(a).tree), normalize(parse_ids(b).tree))
                self.assertTrue(evaluate(a, [b]).structural_match)
        self.assertFalse(evaluate("⿲木日月", ["⿰木日"]).structural_match)
        self.assertFalse(evaluate("⿲木日月", ["⿲木月日"]).structural_match)

    def test_skeleton_and_multiset(self):
        swapped = evaluate("⿰木日", ["⿰日木"])
        self.assertFalse(swapped.structural_match)
        self.assertTrue(swapped.skeleton_accuracy)
        self.assertEqual(swapped.component_f1, 1)
        changed = evaluate("⿰木⿱日月", ["⿰木⿻日月"])
        self.assertFalse(changed.skeleton_accuracy)
        duplicate = evaluate("⿲木木日", ["⿲木日日"])
        self.assertAlmostEqual(duplicate.component_precision, 2 / 3)
        self.assertAlmostEqual(duplicate.component_recall, 2 / 3)
        self.assertAlmostEqual(duplicate.component_f1, 2 / 3)

    def test_context_rules_are_direct_and_position_sensitive(self):
        left = (("H", 0),)
        rules = [FamilyRule(frozenset(("水", "氵")), frozenset((left,))),
                 FamilyRule(frozenset(("氵", "川")), frozenset((left,)))]
        self.assertTrue(evaluate("⿰氵木", ["⿰水木"], family_rules=rules).family_match)
        self.assertFalse(evaluate("⿰木氵", ["⿰木水"], family_rules=rules).family_match)
        self.assertFalse(evaluate("⿰川木", ["⿰水木"], family_rules=rules).family_match)
        self.assertFalse(evaluate("⿱氵木", ["⿱水木"], family_rules=rules).family_match)
        self.assertTrue(evaluate("⿰木日", ["⿰木日"], family_rules=[]).family_match)
        self.assertIsNone(evaluate("木", ["木"]).family_match)
        anywhere = [FamilyRule(frozenset(("金", "釒")), contexts=frozenset((("H", 0),)))]
        self.assertTrue(evaluate("⿱艹⿰金甲", ["⿱艹⿰釒甲"], family_rules=anywhere).family_match)
        self.assertFalse(evaluate("⿱艹⿰甲金", ["⿱艹⿰甲釒"], family_rules=anywhere).family_match)
        root = [FamilyRule(frozenset(("金", "釒")), positions=frozenset(((),)))]
        self.assertFalse(evaluate("金", ["釒"], family_rules=root).family_match)

    def test_multi_reference_and_unknown(self):
        score = evaluate("⿰木日", ["?", "⿱木日", "⿰木日"])
        self.assertEqual(score.reference_statuses, ("unsupported", "valid", "valid"))
        self.assertTrue(score.raw_exact)
        self.assertTrue(score.structural_match)
        self.assertEqual(score.component_f1, 1)
        for prediction, references in (("?", ["?"]), ("⿰木", ["⿰木"]), ("木", ["?"]), ("木", [])):
            score = evaluate(prediction, references, family_rules=[])
            self.assertIsNone(score.raw_exact)
            self.assertIsNone(score.family_match)
            self.assertIsNone(score.component_f1)
        # Scores come from one reference, rather than combining independent maxima.
        score = evaluate("⿰木日", ["木", "⿲木月火"])
        self.assertEqual((score.component_precision, score.component_recall), (0.5, 1.0))

    def test_no_expansion_and_exact_monotonic(self):
        self.assertFalse(evaluate("林", ["⿰木木"]).structural_match)
        for text in ("木", "⿾𠀀", "⿻木日", "⿲木日月", "〾木"):
            score = evaluate(text, ["?", text], family_rules=[])
            self.assertTrue(score.raw_exact)
            self.assertTrue(score.structural_match)
            self.assertTrue(score.family_match)
            self.assertTrue(score.skeleton_accuracy)
            self.assertEqual(score.component_f1, 1)

    def test_ordered_tree_edit(self):
        score = evaluate("木", ["⿱一木"], tree_edit=True)
        self.assertEqual(score.tree_edit_status, "valid")
        self.assertEqual(score.tree_edit_similarity, 0.5)
        score = evaluate("⿰木⿱日月", ["⿲木日月"], tree_edit=True)
        self.assertAlmostEqual(score.tree_edit_similarity, 8 / 9)
        self.assertEqual(evaluate("⿰木日", ["⿰木日"], tree_edit=True).tree_edit_similarity, 1)
        self.assertEqual(evaluate("⿲木日月", ["⿰木⿰日月"], tree_edit=True).tree_edit_similarity, 1)
        self.assertEqual(evaluate("?", ["木"], tree_edit=True).tree_edit_status, "unscorable")
        self.assertEqual(evaluate("⿾" * 64 + "木", ["木"], tree_edit=True).tree_edit_status, "unsupported")
        self.assertEqual(evaluate("木", ["木"]).tree_edit_status, "disabled")
        # Reference distances independently checked against zss 1.2.0 with
        # insert/delete cost 1, substitution cost 2 and child promotion.
        for prediction, reference, distance, nodes in (
            ("木", "⿱一木", 2, 4),
            ("⿰木日", "⿰日木", 2, 6),
            ("⿰木⿱日月", "⿲木日月", 1, 9),
        ):
            with self.subTest(prediction=prediction, reference=reference):
                value = evaluate(prediction, [reference], tree_edit=True).tree_edit_similarity
                self.assertAlmostEqual(value, 1 - distance / nodes)


if __name__ == "__main__":
    unittest.main()
