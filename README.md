# TLA+--Python Studio

A research prototype with a compiler-first design for a deliberately
restricted TLA+ state-machine fragment. The compiler creates a typed AST and
model IR, renders readable Python for inspection, and feeds the IR to a
bounded explicit-state explorer. The verifier does not execute generated
Python from a user-provided specification.

## Compiler and tool capabilities

- Definition collection, expression tokenisation, recursive-descent parsing,
  type checking, typed IR construction, and readable Python rendering.
- Integer and Boolean scalar variables, guards, primed updates, UNCHANGED,
  named actions, Next action selection, arithmetic, comparisons, Boolean
  operators, parentheses, and IF THEN ELSE.
- Compiler inspection: POST /api/compile returns generated Python and a
  serialised typed parse/IR tree.
- Bounded breadth-first explicit-state exploration, state predicates,
  shortest discovered violation traces, labelled edges, and explicit-action
  deadlock detection.
- Deterministic evidence ZIPs that include model text, compiler_ir.json,
  generated Python, graph files, verdict, and run metadata.

**Important scope:** this is not a complete TLA+ interpreter, TLC integration,
temporal/fairness checker, semantic-preservation proof, or scalability claim.
A bounded pass is not a proof.

## Local setup
Backend: `cd backend && pip install -r requirements.txt && python app.py`

Frontend (in another terminal): `cd frontend && npm install && npm start`

## Deploy
Use the root `render.yaml` as a Render Blueprint. The deployment builds the frontend, installs backend dependencies and serves everything through Flask + Waitress.

## Reproduce compiler evidence

Run the backend checks from the repository root:

    python -m pip install -r backend/requirements.txt
    cd backend
    python -m unittest -v test_studio.py
    python evidence/run_comprehensive_evidence.py
    python evidence/run_performance_benchmark.py

The functional driver records parser/AST/IR construction, static rejections,
hand-checkable graph oracles, renderer agreement, deterministic report export,
and local API routes. The timing driver records source and graph sizes,
warm-ups, repetitions, medians, variation, and host metadata for small
families. Its output is a local descriptive measurement, not a comparison
with TLC or another tool.

The design and source-language boundary are documented in
[docs/COMPILER_DESIGN.md](docs/COMPILER_DESIGN.md).

## Optional TLC integration
The optional `POST /api/tlc/run` endpoint is disabled until the server administrator installs Java and an official trusted TLC JAR, then sets `TLC_JAR` to its absolute path. `GET /api/tlc/status` reports availability. TLC requires a module named `Model` with `Init` and `Next`, and optionally a defined named invariant. TLC runs with a 25-second timeout, 256 MB JVM heap and one worker. **Do not expose the TLC endpoint to untrusted public users without container isolation, authentication and rate limits.** The existing Render Python runtime does not automatically contain Java or a TLC JAR.
