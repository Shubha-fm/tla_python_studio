# TLA+ to Python Studio (Research Prototype)

A React and Flask research prototype for converting a **restricted subset** of TLA+ into Python and exploring state transitions.

## Features
- TLA+ to Python conversion (restricted integer/boolean finite-state subset)
- Explicit state-space exploration, state-transition graph, deadlock detection
- State property checking and counterexample paths
- Depth and state limits

**Not a complete TLA+ interpreter or TLC integration.** A bounded pass is not a proof.

## Local setup
Backend: `cd backend && pip install -r requirements.txt && python app.py`

Frontend (in another terminal): `cd frontend && npm install && npm start`

## Deploy
Use the root `render.yaml` as a Render Blueprint. The deployment builds the frontend, installs backend dependencies and serves everything through Flask + Waitress.

## Research reporting
After verifying a model, choose **Download verification report (JSON)** to export the model text, property, state graph, counterexample path, and search bounds. Use these bounds in any published experiment. The verifier is separate from TLC.

## Optional TLC integration
The optional `POST /api/tlc/run` endpoint is disabled until the server administrator installs Java and an official trusted TLC JAR, then sets `TLC_JAR` to its absolute path. `GET /api/tlc/status` reports availability. TLC requires a module named `Model` with `Init` and `Next`, and optionally a defined named invariant. TLC runs with a 25-second timeout, 256 MB JVM heap and one worker. **Do not expose the TLC endpoint to untrusted public users without container isolation, authentication and rate limits.** The existing Render Python runtime does not automatically contain Java or a TLC JAR.
