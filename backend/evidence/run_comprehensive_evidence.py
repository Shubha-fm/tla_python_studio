#!/usr/bin/env python3
"""Repeatable functional evidence for the typed restricted TLA+-to-Python pipeline.

This driver is a regression and oracle suite, not proof of full TLA+ semantics,
TLC agreement, temporal properties, scalability, or refinement correctness.
It records the parser/AST contract, the reference evaluator, renderer checks,
bounded graph results, evidence export, HTTP routes, and unit tests.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
DEFAULT_BACKEND = PACKAGE / "src_snapshot"
if not DEFAULT_BACKEND.is_dir():
    DEFAULT_BACKEND = PACKAGE

PARSER = argparse.ArgumentParser(description=__doc__)
PARSER.add_argument("--backend", type=Path, default=DEFAULT_BACKEND)
PARSER.add_argument("--output", type=Path, default=HERE / "current_comprehensive_evidence.json")
ARGS = PARSER.parse_args()
BACKEND = ARGS.backend.resolve()
sys.path.insert(0, str(BACKEND))

from app import app  # noqa: E402
from reports import make_report  # noqa: E402
from tla_parser import (  # noqa: E402
    BinaryExpr,
    IfExpr,
    TranslationError,
    canonical_state_key,
    compile_tla,
    model_to_tree,
    parse_tla,
    successors,
    tla_to_python_from_string,
    tokenize_expression,
)
from verification import ENGINE_NAME, verify  # noqa: E402


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def source_tree_digest(directory: Path) -> str:
    """Stable digest of the Python source snapshot under test."""
    hasher = hashlib.sha256()
    for path in sorted(directory.glob("*.py")):
        hasher.update(path.name.encode("utf-8") + b"\0")
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def model(name: str, variables: str, init: str, action: str, next_name: str = "Step") -> str:
    return f"""---- MODULE {name} ----
VARIABLES {variables}
Init == {init}
{next_name} == {action}
Next == {next_name}
===="""


def counter_source(maximum: int, name: str = "Counter") -> str:
    return f"""---- MODULE {name} ----
EXTENDS Naturals
VARIABLE count
Init == count = 0
Increment == /\\ count < {maximum}
             /\\ count' = count + 1
Reset == /\\ count = {maximum}
         /\\ count' = 0
Next == Increment \\/ Reset
===="""


PAIR = model(
    "Pair",
    "count, flag",
    "/\\ count = 0\n        /\\ flag = TRUE",
    "/\\ count < 2\n        /\\ count' = count + 1\n        /\\ UNCHANGED flag",
)
TUPLE_UNCHANGED = model(
    "TupleUnchanged",
    "x, y",
    "/\\ x = 0\n        /\\ y = 7",
    "/\\ x < 2\n        /\\ x' = x + 1\n        /\\ UNCHANGED <<y>>",
)
CONDITIONAL = model(
    "Conditional",
    "x",
    "x = 0",
    "/\\ x < 3\n        /\\ x' = IF x = 0 THEN 2 ELSE 0",
)
BOOLEAN_MODULO = model(
    "BooleanModulo",
    "x",
    "x = 0",
    "/\\ (x = 0 \\/ x = 1)\n        /\\ x' = (x + 1) % 3",
)
OLD_STATE_COPY = model(
    "OldStateCopy",
    "x, y",
    "/\\ x = 0\n        /\\ y = 0",
    "/\\ x < 2\n        /\\ x' = x + 1\n        /\\ y' = x",
)
BOOLEAN_STUTTER = model("BooleanStutter", "flag", "flag = TRUE", "UNCHANGED flag")
NESTED_CONDITION = r"""---- MODULE NestedCondition ----
VARIABLES x, y
Init == /\ x = 0 /\ y = 0
Step == /\ x = 0
        /\ x' = IF x = 0 /\ y = 0 THEN 1 ELSE 0
        /\ y' = y
Next == Step
===="""
NESTED_IF = r"""---- MODULE NestedIf ----
VARIABLES x, y
Init == /\ x = 0 /\ y = 0
Step == /\ y < 4
        /\ x' = IF x = 0 THEN IF y = 0 THEN 1 ELSE 2 ELSE 3
        /\ y' = y + 1
Next == Step
===="""
BRANCHING = r"""---- MODULE Branching ----
VARIABLE x
Init == x = 0
Left == /\ x = 0
        /\ x' = 1
Right == /\ x = 0
         /\ x' = 2
Next == Left \/ Right
===="""
SHORTEST_WITNESS = r"""---- MODULE ShortestWitness ----
VARIABLE x
Init == x = 0
FailNow == /\ x = 0
           /\ x' = 2
Slow == /\ x = 0
        /\ x' = 1
Finish == /\ x = 1
          /\ x' = 2
Next == FailNow \/ Slow \/ Finish
===="""


def run_unit_tests() -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", "test_studio.py"],
        cwd=BACKEND,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return result.returncode == 0, result.stdout


class Suite:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, group: str, name: str, fn) -> None:
        try:
            detail = fn()
            self.checks.append({"group": group, "name": name, "passed": True, "detail": detail or {}})
        except Exception as exc:  # Keep failures visible in the persisted evidence.
            self.checks.append(
                {
                    "group": group,
                    "name": name,
                    "passed": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    def expect_error(self, group: str, name: str, fn) -> None:
        try:
            fn()
        except (TranslationError, ValueError, TypeError):
            self.checks.append({"group": group, "name": name, "passed": True})
        except Exception as exc:
            self.checks.append(
                {
                    "group": group,
                    "name": name,
                    "passed": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
        else:
            self.checks.append({"group": group, "name": name, "passed": False, "error": "Expected rejection, but the input was accepted."})


def require(condition: bool, message: str) -> dict:
    if not condition:
        raise AssertionError(message)
    return {}


def check_summary(source: str, property_text: str, expected: dict, **limits) -> dict:
    result = verify(source, property_text, **limits)
    actual = {key: result["summary"][key] for key in expected}
    require(actual == expected, f"expected {expected}, got {actual}")
    return {
        "summary": actual,
        "counterexample": result["counterexample"],
        "deadlock_trace": result["deadlock_trace"],
    }


def check_final_state(source: str, property_text: str, final_state: dict) -> dict:
    result = verify(source, property_text, max_depth=40, max_states=500)
    require(result["nodes"][-1]["state"] == final_state, f"expected final state {final_state}")
    return {"final_state": final_state}


def run_rendered_python(source: str, state: dict) -> list:
    """Run only generator-produced text in a fresh isolated Python process.

    This test validates the renderer. The product verifier does not use this
    path and never executes generated text in its Flask process.
    """
    generated = tla_to_python_from_string(source)
    runner = (
        "import json, runpy, sys\n"
        "namespace = runpy.run_path(sys.argv[1])\n"
        "state = json.loads(sys.argv[2])\n"
        "print(json.dumps(namespace['next_transitions'](state), sort_keys=True))\n"
    )
    with tempfile.TemporaryDirectory(prefix="tla_renderer_") as temporary:
        target = Path(temporary) / "generated_model.py"
        target.write_text(generated, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-I", "-c", runner, str(target), json.dumps(state, sort_keys=True)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode != 0:
        raise AssertionError(f"rendered Python failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def check_renderer_agreement(source: str, state: dict) -> dict:
    model_ir = parse_tla(source)
    expected = json.loads(json.dumps(successors(model_ir, state), sort_keys=True))
    actual = run_rendered_python(source, state)
    require(actual == expected, f"renderer disagrees with typed evaluator: {actual} != {expected}")
    return {"transitions": actual}


def api_json(client, route: str, payload: dict):
    response = client.post(route, json=payload)
    return response, response.get_json(silent=True)


def main() -> None:
    suite = Suite()
    finite = {"states": 3, "transitions": 2, "truncated": False, "deadlocks": 1, "property_status": "pass_finite_graph"}

    # RQ1: grammar, typed AST/IR, and restricted language behaviour.
    suite.add(
        "parser_and_ast",
        "typed_initial_state",
        lambda: (lambda ir: require(ir.variable_types == {"count": "int", "flag": "bool"}, "unexpected inferred types"))(parse_tla(PAIR)),
    )
    suite.add("parser_and_ast", "integer_literal_and_addition", lambda: check_summary(model("Add", "x", "x = 0", "/\\ x < 2\n        /\\ x' = x + 1"), "x >= 0", finite, max_depth=40, max_states=500))
    suite.add("parser_and_ast", "boolean_literal_and_scalar_unchanged", lambda: check_summary(BOOLEAN_STUTTER, "flag = TRUE", {"states": 1, "transitions": 1, "truncated": False, "deadlocks": 0, "property_status": "pass_finite_graph"}, max_depth=40, max_states=500))

    def comparisons() -> dict:
        cases = [
            ("<", "x < 1", "1", "x >= 0"),
            ("<=", "x <= 0", "1", "x >= 0"),
            (">", "x > -1", "-1", "x >= -1"),
            (">=", "x >= 0", "-1", "x >= -1"),
            ("=", "x = 0", "1", "x >= 0"),
            ("/=", "x /= 1", "1", "x >= 0"),
        ]
        for label, guard, update, property_text in cases:
            graph = verify(model(f"Compare{label}", "x", "x = 0", f"/\\ {guard}\n        /\\ x' = {update}"), property_text, 40, 500)
            require(graph["summary"]["states"] == 2 and graph["summary"]["transitions"] == 1, f"comparison {label} failed")
        return {"operators": [case[0] for case in cases]}

    suite.add("parser_and_ast", "all_comparison_operators", comparisons)
    suite.add("parser_and_ast", "subtraction_and_multiplication", lambda: check_summary(model("Math", "x", "x = 3", "/\\ x < 6\n        /\\ x' = (x * 2) - 1"), "x > 0", {"states": 3, "transitions": 2, "truncated": False, "deadlocks": 1, "property_status": "pass_finite_graph"}, max_depth=40, max_states=500))
    suite.add("parser_and_ast", "boolean_or_modulo_and_negation", lambda: check_summary(BOOLEAN_MODULO, "~(x < 0)", finite, max_depth=40, max_states=500))
    suite.add("parser_and_ast", "conditional_expression", lambda: check_summary(CONDITIONAL, "x >= 0", {"states": 2, "transitions": 2, "truncated": False, "deadlocks": 0, "property_status": "pass_finite_graph"}, max_depth=40, max_states=500))
    suite.add("parser_and_ast", "nested_boolean_condition_in_if", lambda: check_final_state(NESTED_CONDITION, "x >= 0", {"x": 1, "y": 0}))
    suite.add("parser_and_ast", "nested_if_expression", lambda: check_final_state(NESTED_IF, "x >= 0", {"x": 3, "y": 4}))
    suite.add("parser_and_ast", "tuple_unchanged", lambda: check_summary(TUPLE_UNCHANGED, "y = 7", finite, max_depth=40, max_states=500))
    suite.add("parser_and_ast", "old_state_read", lambda: check_final_state(OLD_STATE_COPY, "y <= x", {"x": 2, "y": 1}))
    suite.add(
        "parser_and_ast",
        "named_action_disjunction_and_labels",
        lambda: (lambda result: require({edge["action"] for edge in result["edges"]} == {"Increment", "Reset"}, "expected both action labels"))(verify(counter_source(2, "Labelled"), "count >= 0", max_depth=40, max_states=500)),
    )
    suite.add(
        "parser_and_ast",
        "ast_contains_conditional_and_conjunction",
        lambda: (lambda update: require(isinstance(update, IfExpr) and isinstance(update.condition, BinaryExpr) and update.condition.operator == "/\\", "unexpected AST shape"))(parse_tla(NESTED_CONDITION).actions[0].updates["x"]),
    )
    suite.add(
        "parser_and_ast",
        "generated_python_is_inspection_only",
        lambda: (lambda output: require("exec(" not in output and "eval(" not in output and "does not execute generated text" in output, "unsafe renderer text"))(tla_to_python_from_string(counter_source(2))),
    )

    # The compiler pipeline is exposed as inspectable artefacts, not just text.
    suite.add(
        "compiler_pipeline",
        "lexer_tokens_and_columns",
        lambda: (lambda tokens: require(
            [token["text"] for token in tokens] == ["count", "+", "10", "<=", "20", "/\\", "~", "(", "count", "=", "1", ")"]
            and tokens[0]["column"] == 1
            and tokens[5]["kind"] == "operator",
            "unexpected lexer token stream",
        ))(tokenize_expression("count + 10 <= 20 /\\ ~(count = 1)")),
    )
    suite.add(
        "compiler_pipeline",
        "parse_tree_serialises_actions_and_types",
        lambda: (lambda tree: require(
            tree["kind"] == "model"
            and tree["variables"] == [{"name": "count", "type": "int", "initial": 0}]
            and tree["next_actions"] == ["Increment", "Reset"]
            and tree["actions"][0]["updates"]["count"]["kind"] == "binary",
            "unexpected serialised compiler tree",
        ))(model_to_tree(parse_tla(counter_source(2, "Tree")))),
    )
    suite.add(
        "compiler_pipeline",
        "compile_artifact_links_source_ir_and_target",
        lambda: (lambda compilation: require(
            compilation.source == counter_source(2, "Compilation")
            and compilation.model.initial_state == {"count": 0}
            and "# Action: Increment" in compilation.python,
            "compiler artefacts disagree",
        ))(compile_tla(counter_source(2, "Compilation"))),
    )
    suite.add(
        "compiler_pipeline",
        "compilation_is_deterministic_for_fixed_source",
        lambda: require(
            compile_tla(NESTED_IF).python == compile_tla(NESTED_IF).python,
            "fixed source produced different rendered target text",
        ),
    )
    def syntax_diagnostic() -> dict:
        source = "---- MODULE Syntax ----\nVARIABLE x\nInit == x = 0\nStep == x' = (x + )\nNext == Step\n===="
        try:
            parse_tla(source)
        except TranslationError as exc:
            return require("column" in str(exc) and "Expected" in str(exc), "missing local syntax diagnostic")
        raise AssertionError("malformed expression was accepted")

    suite.add("compiler_pipeline", "diagnostic_reports_source_column", syntax_diagnostic)

    # RQ2: hand-checkable graph and verdict oracles.
    suite.add("exploration_and_oracles", "finite_graph_pass", lambda: check_summary(counter_source(39, "Cycle39"), "count >= 0", {"states": 40, "transitions": 40, "truncated": False, "deadlocks": 0, "property_status": "pass_finite_graph"}, max_depth=40, max_states=500))
    suite.add("exploration_and_oracles", "depth_cutoff", lambda: check_summary(counter_source(50, "Cutoff"), "count >= 0", {"states": 41, "transitions": 40, "truncated": True, "deadlocks": 0, "property_status": "bounded_pass"}, max_depth=40, max_states=500))
    suite.add("exploration_and_oracles", "zero_depth_cutoff", lambda: check_summary(counter_source(2, "DepthZero"), "count >= 0", {"states": 1, "transitions": 0, "truncated": True, "deadlocks": 0, "property_status": "bounded_pass"}, max_depth=0, max_states=500))
    suite.add("exploration_and_oracles", "state_budget_cutoff", lambda: check_summary(counter_source(2, "StateOne"), "count >= 0", {"states": 1, "transitions": 0, "truncated": True, "deadlocks": 0, "property_status": "bounded_pass"}, max_depth=40, max_states=1))
    suite.add("exploration_and_oracles", "property_violation_trace", lambda: (lambda result: require(result["counterexample"] == [0, 1, 2] and result["summary"]["property_status"] == "violation", "expected a three-node violation witness"))(verify(counter_source(3, "Violation"), "count < 2", max_depth=40, max_states=500)))
    suite.add("exploration_and_oracles", "deadlock_trace", lambda: (lambda result: require(result["deadlock_trace"] == [0, 1, 2], "expected a three-node deadlock trace"))(verify(PAIR, "flag = TRUE", max_depth=40, max_states=500)))
    suite.add("exploration_and_oracles", "branching_graph_oracle", lambda: check_summary(BRANCHING, "x >= 0", {"states": 3, "transitions": 2, "truncated": False, "deadlocks": 2, "property_status": "pass_finite_graph"}, max_depth=40, max_states=500))
    suite.add("exploration_and_oracles", "breadth_first_shortest_witness", lambda: (lambda result: require(result["counterexample"] == [0, 1], "expected the one-step witness to x = 2"))(verify(SHORTEST_WITNESS, "x < 2", max_depth=40, max_states=500)))

    # RQ3: explicit rejections and exact source-value types.
    invalid = {
        "no_variables": "INVALID",
        "duplicate_variable": "---- MODULE Duplicate ----\nVARIABLES x, x\nInit == x = 0\nStep == x' = x\nNext == Step\n====",
        "missing_init": "---- MODULE MissingInit ----\nVARIABLE x\nStep == x' = x\nNext == Step\n====",
        "missing_next": "---- MODULE MissingNext ----\nVARIABLE x\nInit == x = 0\n====",
        "partial_init": r"""---- MODULE Partial ----
VARIABLES x, y
Init == x = 0
Step == /\ x' = x
        /\ y' = y
Next == Step
====""",
        "duplicate_init": r"""---- MODULE InitTwice ----
VARIABLE x
Init == /\ x = 0
        /\ x = 1
Step == x' = x
Next == Step
====""",
        "unknown_guard_symbol": r"""---- MODULE Unknown ----
VARIABLE x
Init == x = 0
Step == /\ FOO
        /\ x' = x
Next == Step
====""",
        "primed_rhs": r"""---- MODULE Primed ----
VARIABLES x, y
Init == /\ x = 0
        /\ y = 0
Step == /\ x' = x + 1
        /\ y' = x'
Next == Step
====""",
        "missing_next_assignment": r"""---- MODULE MissingAssign ----
VARIABLES x, y
Init == /\ x = 0
        /\ y = 0
Step == x' = x + 1
Next == Step
====""",
        "unknown_next_action": "---- MODULE BadNext ----\nVARIABLE x\nInit == x = 0\nNext == Nope\n====",
        "inline_next_relation": r"""---- MODULE InlineNext ----
VARIABLE x
Init == x = 0
Next == /\ x' = x + 1
====""",
        "boolean_arithmetic": "---- MODULE BoolArithmetic ----\nVARIABLE b\nInit == b = TRUE\nStep == b' = b + 1\nNext == Step\n====",
        "boolean_integer_assignment": "---- MODULE BoolInt ----\nVARIABLE b\nInit == b = TRUE\nStep == b' = 1\nNext == Step\n====",
        "mixed_type_equality": "---- MODULE MixedEquality ----\nVARIABLES b, x\nInit == /\\ b = TRUE\n        /\\ x = 0\nStep == /\\ b = x\n        /\\ UNCHANGED <<b, x>>\nNext == Step\n====",
        "conditional_branch_type_mismatch": "---- MODULE BranchType ----\nVARIABLE x\nInit == x = 0\nStep == x' = IF x = 0 THEN 1 ELSE TRUE\nNext == Step\n====",
        "non_boolean_guard": "---- MODULE NumericGuard ----\nVARIABLE x\nInit == x = 0\nStep == /\\ x + 1\n        /\\ x' = x\nNext == Step\n====",
    }
    for name, source in invalid.items():
        suite.expect_error("rejections_and_types", name, lambda source=source: parse_tla(source))
    suite.expect_error("rejections_and_types", "unsupported_property", lambda: verify(counter_source(2), "count' = 0", max_depth=40, max_states=500))
    suite.expect_error("rejections_and_types", "non_boolean_property", lambda: verify(counter_source(2), "count + 1", max_depth=40, max_states=500))
    suite.add(
        "rejections_and_types",
        "canonical_key_uses_exact_declared_type",
        lambda: (lambda ir: require(canonical_state_key(ir, ir.initial_state) != (("flag", "int", 1),), "Boolean and integer key collision"))(parse_tla(BOOLEAN_STUTTER)),
    )

    # Renderer agreement is independent of the in-process verifier path.
    suite.add("renderer_subprocess", "counter_renderer_matches_ir", lambda: check_renderer_agreement(counter_source(2), {"count": 0}))
    suite.add("renderer_subprocess", "nested_condition_renderer_matches_ir", lambda: check_renderer_agreement(NESTED_CONDITION, {"x": 0, "y": 0}))
    suite.add("renderer_subprocess", "boolean_renderer_matches_ir", lambda: check_renderer_agreement(BOOLEAN_STUTTER, {"flag": True}))

    # Deterministic report contents and local provenance.
    def report_contents() -> dict:
        report = make_report(counter_source(3, "Report"), "count >= 0", max_depth=40, max_states=500)
        with zipfile.ZipFile(io.BytesIO(report)) as archive:
            names = archive.namelist()
            manifest = json.loads(archive.read("run_manifest.json"))
        expected_names = ["README.md", "compiler_ir.json", "generated_model.py", "model.tla", "run_manifest.json", "states.csv", "transitions.csv", "verification.json"]
        require(names == expected_names, f"unexpected ZIP entries: {names}")
        require(manifest["complete"] is True and manifest["engine"] == ENGINE_NAME and manifest["semantic_contract"] == "typed_restricted_tla_ast_ir_v2", "missing report provenance")
        require(manifest["generated_python_execution"] == "not used by the verifier", "missing execution boundary")
        return {"archive_entries": names, "report_sha256": digest(report)}

    suite.add("evidence_export", "report_contents_and_manifest", report_contents)
    suite.add("evidence_export", "deterministic_report_bytes", lambda: require(make_report(counter_source(3, "Report"), "count >= 0", 40, 500) == make_report(counter_source(3, "Report"), "count >= 0", 40, 500), "reports differ"))

    # HTTP contract via Flask's local test client only.
    client = app.test_client()
    suite.add("http_api", "health", lambda: (lambda response: require(response.status_code == 200 and response.get_json().get("ok") is True and response.get_json().get("version") == "5.0" and response.get_json().get("compiler_contract") == "restricted_tla_typed_ast_ir_v2", "health endpoint failed"))(client.get("/api/health")))
    suite.add("http_api", "convert_accepted", lambda: (lambda response, data: require(response.status_code == 200 and data.get("ok") is True and "output" in data and "typed IR" in data["warnings"][0] and data["compiler"]["contract"] == "restricted_tla_typed_ast_ir_v2", "convert endpoint failed"))(*api_json(client, "/api/convert", {"code": counter_source(2), "mode": "tla"})))
    suite.add("http_api", "compile_returns_typed_tree", lambda: (lambda response, data: require(response.status_code == 200 and data.get("ok") is True and data["ir"]["kind"] == "model" and data["ir"]["next_actions"] == ["Increment", "Reset"], "compile endpoint failed"))(*api_json(client, "/api/compile", {"code": counter_source(2), "mode": "tla"})))
    suite.add("http_api", "convert_rejects_bad_source", lambda: (lambda response, data: require(response.status_code == 422 and "error" in data, "expected conversion rejection"))(*api_json(client, "/api/convert", {"code": "INVALID", "mode": "tla"})))
    suite.add("http_api", "convert_rejects_other_mode", lambda: (lambda response, data: require(response.status_code == 422 and "error" in data, "expected mode rejection"))(*api_json(client, "/api/convert", {"code": counter_source(2), "mode": "lean"})))
    suite.add("http_api", "verify_accepted", lambda: (lambda response, data: require(response.status_code == 200 and data.get("ok") is True and data["summary"]["engine"] == ENGINE_NAME and data["summary"]["property_status"] == "pass_finite_graph", "verify endpoint failed"))(*api_json(client, "/api/verify", {"code": counter_source(2), "property": "count >= 0", "max_depth": 40, "max_states": 500})))
    suite.add("http_api", "verify_rejects_invalid_limits", lambda: (lambda response, data: require(response.status_code == 422 and "error" in data, "expected limit rejection"))(*api_json(client, "/api/verify", {"code": counter_source(2), "max_depth": 41, "max_states": 500})))

    def report_route() -> dict:
        response = client.post("/api/report", json={"code": counter_source(2), "property": "count >= 0", "max_depth": 40, "max_states": 500})
        require(response.status_code == 200 and response.mimetype == "application/zip", "report route did not return ZIP")
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            require("verification.json" in archive.namelist(), "report ZIP lacks verdict")
        return {"bytes": len(response.data)}

    suite.add("http_api", "report_zip", report_route)
    suite.add("http_api", "tlc_status_disabled", lambda: (lambda response: require(response.status_code == 200 and response.get_json().get("available") is False, "TLC status should be disabled"))(client.get("/api/tlc/status")))
    suite.add("http_api", "tlc_run_rejected", lambda: (lambda response, data: require(response.status_code == 422 and "error" in data, "TLC run should be rejected"))(*api_json(client, "/api/tlc/run", {"code": counter_source(2)})))

    passed_tests, unit_output = run_unit_tests()
    suite.checks.append({"group": "regression_suite", "name": "bundled_unit_tests", "passed": passed_tests, "detail": {"output": unit_output}})

    totals = Counter(check["group"] for check in suite.checks)
    passed = Counter(check["group"] for check in suite.checks if check["passed"])
    output = {
        "scope": "Typed parser/AST, reference evaluator, renderer, bounded explorer, evidence export, local API, and bundled unit tests.",
        "not_claimed": "Exhaustive testing, full TLA+ semantics, temporal checking, TLC equivalence, performance, deployment safety, or a refinement proof.",
        "source_snapshot_sha256": source_tree_digest(BACKEND),
        "source_snapshot_path": BACKEND.name,
        "python_version": platform.python_version(),
        "checks": suite.checks,
        "groups": [
            {"group": group, "total": totals[group], "passed": passed[group], "failed": totals[group] - passed[group]}
            for group in sorted(totals)
        ],
        "summary": {
            "total": len(suite.checks),
            "passed": sum(check["passed"] for check in suite.checks),
            "failed": sum(not check["passed"] for check in suite.checks),
        },
    }
    ARGS.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2, sort_keys=True))
    if output["summary"]["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

