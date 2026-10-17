"""Focused unit tests for the typed front end and bounded explorer."""
import unittest

from tla_parser import (
    TranslationError,
    canonical_state_key,
    compile_tla,
    model_to_tree,
    parse_tla,
    successors,
    syntax_contract,
    tla_to_python_from_string,
    tokenize_expression,
)
from verification import verify


SOURCE = """---- MODULE Counter ----
EXTENDS Naturals
VARIABLE count
Init == count = 0
Increment == /\\ count < 3
             /\\ count' = count + 1
Reset == /\\ count = 3
         /\\ count' = 0
Next == Increment \\/ Reset
===="""


class StudioTests(unittest.TestCase):
    def test_translator(self):
        output = tla_to_python_from_string(SOURCE)
        self.assertIn("INITIAL_STATE", output)
        self.assertIn("def next_states", output)

    def test_graph(self):
        result = verify(SOURCE, "count >= 0")
        self.assertEqual(result["summary"]["states"], 4)
        self.assertEqual(result["summary"]["transitions"], 4)
        self.assertTrue(all(edge.get("action") in ("Increment", "Reset") for edge in result["edges"]))
        self.assertEqual(result["summary"]["property_status"], "pass_finite_graph")

    def test_counterexample(self):
        result = verify(SOURCE, "count < 2")
        self.assertEqual(result["summary"]["property_status"], "violation")
        self.assertEqual(result["counterexample"], [0, 1, 2])

    def test_unchanged_variable(self):
        source = """---- MODULE Pair ----
VARIABLES count, flag
Init == /\\ count = 0
        /\\ flag = TRUE
Step == /\\ count < 2
        /\\ count' = count + 1
        /\\ UNCHANGED flag
Next == Step
===="""
        result = verify(source, "flag = TRUE")
        self.assertEqual(result["summary"]["states"], 3)
        self.assertEqual(result["summary"]["deadlocks"], 1)

    def test_conditional_expression(self):
        source = """---- MODULE Choice ----
VARIABLE x
Init == x = 0
Toggle == /\\ x < 3
          /\\ x' = IF x = 0 THEN 2 ELSE 0
Next == Toggle
===="""
        graph = verify(source, "x >= 0")
        self.assertEqual(graph["summary"]["states"], 2)
        self.assertEqual(graph["summary"]["transitions"], 2)

    def test_boolean_expression(self):
        source = """---- MODULE BoolOp ----
VARIABLE x
Init == x = 0
Step == /\\ (x = 0 \\/ x = 1)
        /\\ x' = (x + 1) % 3
Next == Step
===="""
        graph = verify(source, "~(x < 0)")
        self.assertEqual(graph["summary"]["states"], 3)
        self.assertEqual(graph["summary"]["deadlocks"], 1)

    def test_invalid_input(self):
        with self.assertRaises(TranslationError):
            tla_to_python_from_string("INVALID")
        with self.assertRaises(TranslationError):
            parse_tla("---- MODULE Reserved ----\nVARIABLE TRUE\nInit == TRUE = TRUE\nStep == TRUE' = TRUE\nNext == Step\n====")

    def test_nested_boolean_condition_builds_typed_ir(self):
        source = r"""---- MODULE Nested ----
VARIABLES x, y
Init == /\ x = 0 /\ y = 0
Step == /\ x' = IF x = 0 /\ y = 0 THEN 1 ELSE 0
        /\ y' = y
Next == Step
===="""
        model = parse_tla(source)
        self.assertEqual(successors(model, model.initial_state), [("Step", {"x": 1, "y": 0})])
        self.assertEqual(model.actions[0].name, "Step")

    def test_inline_next_relation_is_rejected(self):
        source = r"""---- MODULE InlineNext ----
VARIABLE x
Init == x = 0
Next == /\ x' = x + 1
===="""
        with self.assertRaises(TranslationError):
            parse_tla(source)

    def test_boolean_integer_mixing_is_rejected(self):
        source = """---- MODULE BoolArithmetic ----
VARIABLE b
Init == b = TRUE
Step == b' = b + 1
Next == Step
===="""
        with self.assertRaises(TranslationError):
            parse_tla(source)

    def test_state_key_checks_exact_type(self):
        model = parse_tla(SOURCE)
        with self.assertRaises(TranslationError):
            canonical_state_key(model, {"count": True})

    def test_generated_text_is_syntax_checked_not_executed_by_verifier(self):
        output = tla_to_python_from_string(SOURCE)
        self.assertIn("def next_transitions", output)
        self.assertIn("does not execute generated text", output)
        compile(output, "<test-generated>", "exec")

    def test_lexer_exposes_tla_tokens_and_one_based_columns(self):
        tokens = tokenize_expression("count + 10 <= 20 /\\ ~(count = 1)")
        self.assertEqual([token["text"] for token in tokens], ["count", "+", "10", "<=", "20", "/\\", "~", "(", "count", "=", "1", ")"])
        self.assertEqual(tokens[0]["column"], 1)
        self.assertEqual(tokens[5]["kind"], "operator")
        contract = syntax_contract()
        self.assertEqual(contract["id"], "restricted_tla_to_python_v1")
        self.assertEqual(len(contract["accepted_forms"]), 22)
        self.assertIn(
            {"source": "IF condition THEN yes ELSE no", "parser": "_parse_if creates IfExpr; branches recurse", "ir": "IfExpr with Boolean condition and equal branch types", "python": "(<yes> if <condition> else <no>)"},
            contract["accepted_forms"],
        )

    def test_compiler_result_links_source_ir_and_readable_target(self):
        compilation = compile_tla(SOURCE)
        self.assertEqual(compilation.source, SOURCE)
        self.assertEqual(compilation.model.initial_state, {"count": 0})
        self.assertIn("# Action: Increment", compilation.python)

    def test_model_tree_is_json_shaped_and_names_next_actions(self):
        tree = model_to_tree(parse_tla(SOURCE))
        self.assertEqual(tree["kind"], "model")
        self.assertEqual(tree["variables"], [{"name": "count", "type": "int", "initial": 0}])
        self.assertEqual(tree["next_actions"], ["Increment", "Reset"])
        self.assertEqual(tree["actions"][0]["updates"]["count"]["kind"], "binary")


if __name__ == "__main__":
    unittest.main()
