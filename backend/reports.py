"""Deterministic, downloadable compiler and explorer evidence bundles."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import platform
import zipfile

from tla_parser import compile_tla, model_to_tree, syntax_contract
from verification import verify


SEMANTIC_CONTRACT = "typed_restricted_tla_ast_ir_v2"


def make_report(source: str, property_text: str = "", max_depth: int = 12, max_states: int = 120) -> bytes:
    """Create deterministic evidence for one compiler/explorer run.

    The archive deliberately records the IR tree separately from readable
    generated Python.  This makes it clear that the graph verdict came from
    the typed IR evaluator rather than dynamic execution of target text.
    """
    if not isinstance(source, str) or not source.strip():
        raise ValueError("A TLA+ specification is required.")
    compilation = compile_tla(source)
    graph = verify(source, property_text, max_depth, max_states)
    source_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    settings = {
        "engine": graph["summary"]["engine"],
        "semantic_contract": SEMANTIC_CONTRACT,
        "compiler_phases": ["definition_collection", "lex_parse", "type_check", "typed_ir", "python_render"],
        "generated_python_execution": "not used by the verifier",
        "max_depth": max_depth,
        "max_states": max_states,
        "property": property_text,
        "source_sha256": source_sha,
        "python_version": platform.python_version(),
        "complete": not graph["summary"]["truncated"],
    }

    memo = io.StringIO()
    memo.write("# Compiler and verification evidence\n\n")
    memo.write("This run uses a typed restricted-TLA+ compiler and IR explorer, not TLC.\n\n")
    memo.write("`compiler_ir.json` is the checked parse/IR tree. `syntax_mapping.json` lists every accepted source form and its Python lowering. `generated_model.py` is an inspection artefact; the verifier does not execute it.\n\n")
    memo.write(f"Model SHA-256: {source_sha}\n\n")
    for key, value in graph["summary"].items():
        memo.write(f"- {key}: {value}\n")
    memo.write("\nA complete state graph is limited to the explored finite reachable graph.\n")

    def csv_text(header: list[str], rows) -> str:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)
        return stream.getvalue()

    transitions = csv_text(
        ["source", "target", "action"],
        ((edge["source"], edge["target"], edge.get("action", "")) for edge in graph["edges"]),
    )
    states = csv_text(
        ["id", "depth", "state_json"],
        ((node["id"], node["depth"], json.dumps(node["state"], sort_keys=True)) for node in graph["nodes"]),
    )
    files = {
        "README.md": memo.getvalue(),
        "compiler_ir.json": json.dumps(model_to_tree(compilation.model), indent=2, sort_keys=True),
        "syntax_mapping.json": json.dumps(syntax_contract(), indent=2, sort_keys=True),
        "generated_model.py": compilation.python,
        "model.tla": source,
        "run_manifest.json": json.dumps(settings, indent=2, sort_keys=True),
        "states.csv": states,
        "transitions.csv": transitions,
        "verification.json": json.dumps(graph, indent=2, sort_keys=True),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, content in sorted(files.items()):
            info = zipfile.ZipInfo(filename, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content.encode("utf-8"))
    return buffer.getvalue()
