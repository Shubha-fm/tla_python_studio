# TLA+ to Python Research Studio

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
