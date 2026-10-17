# Restricted TLA+ compiler design

## Purpose

TLA+--Python Studio is a research prototype with a deliberately narrow source
language. It is a compiler in the restricted-language sense: it turns a stated
source grammar into a checked, typed intermediate representation (IR) and a
readable target artefact. It is not a full TLA+ implementation and it does not
claim source-to-target semantic preservation.

The compiler is deliberately separated from the verification tool:

- The compiler owns source collection, tokenisation, recursive-descent parsing,
  static/type checks, IR construction, parse-tree inspection, and Python
  rendering.
- The tool owns HTTP responses, bounded breadth-first graph exploration,
  witnesses, report export, and UI integration.
- The verifier evaluates the typed IR. It does not execute generated Python
  from a user-provided specification.

## Source contract

The supported fragment has one VARIABLE or VARIABLES declaration, an Init
definition, named actions, and a Next definition that names one or more
actions. A variable starts as an integer or Boolean literal. Actions contain
Boolean guards, primed assignments, and UNCHANGED clauses. Expressions support
integer arithmetic, comparison, Boolean conjunction/disjunction/negation,
parentheses, and IF THEN ELSE.

Sets, functions, records, quantifiers, temporal formulas, fairness, general
modules, and arbitrary TLA+ operators are intentionally outside the contract.

## Pipeline

1. Definition collection strips line comments, finds the variable declaration,
   and records named top-level definitions. It rejects duplicate definitions.
2. Lexical analysis scans expression tokens without using Python's expression
   parser. Tokens carry a one-based source column for diagnostics.
3. Recursive-descent parsing applies the documented precedence levels and
   produces immutable Literal, Variable, Unary, Binary, and If AST nodes.
4. Semantic analysis resolves variables and checks the small two-type system:
   int and bool. It checks total initial states, total action updates, named
   Next actions, old-state reads, guards, and update types.
5. IR lowering creates ModelIR with ordered variables, declared types, a total
   initial state, checked actions, and the selected Next action names.
6. Target rendering produces readable Python and runs Python compile only as a
   syntax check. The output is never executed by the in-process verifier.

The public compile_tla function returns source, ModelIR, and readable Python.
model_to_tree serialises the checked IR and embedded AST nodes as JSON-safe
data for the compiler-inspection API and evidence archives.

## Semantic rules

Every action reads the old state. For an enabled action a and source state s,
the successor assigns each variable v from eval(update_a(v), s). No update can
observe a preceding update in the same action. UNCHANGED creates an explicit
old-state variable expression.

The canonical state key includes variable name, declared type, and value. This
prevents Python's equality between True and 1 from merging Boolean and integer
states.

## Tool and evidence boundary

POST /api/convert returns the readable target and compiler metadata.
POST /api/compile additionally returns the serialised tree. POST /api/verify
compiles the model, parses an optional Boolean state predicate, and performs
bounded breadth-first exploration of the IR. A finite graph pass, bounded
pass, violation, and explicit-action deadlock are documented separately in
the manuscript and report manifest.

The report endpoint creates a deterministic ZIP with:

- model.tla;
- compiler_ir.json;
- generated_model.py;
- state and transition CSV files;
- verification.json; and
- a manifest that identifies the typed-IR engine and says that generated
  Python was not executed by the verifier.

## Tests and timing

From the repository root, run:

    python -m pip install -r backend/requirements.txt
    cd backend
    python -m unittest -v test_studio.py
    python evidence/run_comprehensive_evidence.py
    python evidence/run_performance_benchmark.py

The functional driver exercises accepted syntax, AST/IR shape, diagnostics,
static rejections, small graph oracles, renderer agreement in an isolated
child process, report determinism, local API contracts, and unit tests. The
timing driver records source sizes, graph sizes, warm-ups, repetitions,
medians, dispersion, and host metadata. Timing output is a single-machine
description, not a performance comparison or scalability claim.

## Extension rule

Any grammar extension should add a lexical rule, AST node or case, static type
rule, IR/evaluator rule, renderer rule, positive test, negative test, and
documentation update. If it changes the source contract, add a small
hand-checkable graph oracle before relying on larger experiments.
