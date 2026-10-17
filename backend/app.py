"""HTTP boundary for the restricted compiler and bounded explorer."""
from __future__ import annotations

import io
import os

from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

from reports import make_report
from tla_parser import TranslationError, compile_tla, model_to_tree
from tlc_runner import run_tlc, tlc_status
from verification import verify


ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(ROOT, "..", "frontend", "build")
APP_VERSION = "5.0"
COMPILER_CONTRACT = "restricted_tla_typed_ast_ir_v2"

app = Flask(__name__, static_folder=FRONTEND, static_url_path="/")
CORS(app, origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","))
app.config["MAX_CONTENT_LENGTH"] = 250_000


def _payload() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise TranslationError("Provide a JSON object.")
    return data


def _compile_payload(data: dict, include_tree: bool = False) -> dict:
    if data.get("mode", "tla") != "tla":
        raise TranslationError("Lean conversion is not implemented.")
    compilation = compile_tla(data.get("code", ""))
    response: dict = {
        "output": compilation.python,
        "compiler": {
            "contract": COMPILER_CONTRACT,
            "phases": ["definition_collection", "lex_parse", "type_check", "typed_ir", "python_render"],
            "verification_execution": "typed IR only; generated Python is not executed by the verifier",
        },
        "warnings": [
            "Restricted typed TLA+ subset only. The Python rendering is for inspection; "
            "verification evaluates the typed IR directly."
        ],
    }
    if include_tree:
        response["ir"] = model_to_tree(compilation.model)
    return response


@app.get("/api/health")
def health():
    return jsonify(ok=True, service="TLA+ Python Studio", version=APP_VERSION, compiler_contract=COMPILER_CONTRACT)


@app.post("/api/convert")
def convert():
    try:
        return jsonify(ok=True, **_compile_payload(_payload(), include_tree=False))
    except TranslationError as exc:
        return jsonify(ok=False, error=str(exc)), 422


@app.post("/api/compile")
def compile_model():
    """Return generated Python plus a serialised typed parse/IR tree."""
    try:
        return jsonify(ok=True, **_compile_payload(_payload(), include_tree=True))
    except TranslationError as exc:
        return jsonify(ok=False, error=str(exc)), 422


@app.post("/api/verify")
def verification():
    try:
        data = _payload()
        return jsonify(
            ok=True,
            **verify(
                data.get("code", ""),
                data.get("property", ""),
                data.get("max_depth", 12),
                data.get("max_states", 120),
            ),
        )
    except (TranslationError, ValueError, SyntaxError, TypeError) as exc:
        return jsonify(ok=False, error=str(exc)), 422


@app.post("/api/report")
def evidence_report():
    try:
        data = _payload()
        package = make_report(
            data.get("code", ""),
            data.get("property", ""),
            data.get("max_depth", 12),
            data.get("max_states", 120),
        )
        return send_file(
            io.BytesIO(package),
            mimetype="application/zip",
            as_attachment=True,
            download_name="tla_python_evidence.zip",
        )
    except (TranslationError, ValueError, SyntaxError, TypeError) as exc:
        return jsonify(ok=False, error=str(exc)), 422


@app.get("/api/tlc/status")
def tlc_availability():
    return jsonify(ok=True, **tlc_status())


@app.post("/api/tlc/run")
def tlc_run():
    try:
        data = _payload()
        return jsonify(ok=True, **run_tlc(data.get("code", ""), data.get("invariant", "")))
    except (TranslationError, ValueError) as exc:
        return jsonify(ok=False, error=str(exc)), 422


@app.get("/")
def index():
    return send_from_directory(FRONTEND, "index.html")


@app.get("/<path:path>")
def static_files(path: str):
    if path.startswith("api/"):
        return jsonify(error="Not found"), 404
    file = os.path.join(FRONTEND, path)
    return send_from_directory(FRONTEND, path if os.path.isfile(file) else "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5050")), debug=os.environ.get("FLASK_DEBUG") == "1")
