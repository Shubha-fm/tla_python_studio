#!/usr/bin/env python3
"""Repeatable, single-machine timings for the restricted compiler and explorer.

The results are descriptive measurements for the recorded source revision and
machine.  They are not a comparison with TLC, a scalability claim, or a
substitute for semantic validation.  The driver reports warm-up count,
repetitions, source sizes, graph sizes, and medians so that the experiment can
be repeated or extended without turning one timing run into a general claim.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Callable, TypeVar


HERE = Path(__file__).resolve().parent
DEFAULT_BACKEND = HERE.parent / "src_snapshot"
if not DEFAULT_BACKEND.is_dir():
    DEFAULT_BACKEND = HERE.parent

PARSER = argparse.ArgumentParser(description=__doc__)
PARSER.add_argument("--backend", type=Path, default=DEFAULT_BACKEND, help="Directory containing tla_parser.py and verification.py.")
PARSER.add_argument("--output", type=Path, default=HERE / "current_performance_evidence.json", help="JSON output path.")
PARSER.add_argument("--csv-output", type=Path, default=HERE / "current_performance_evidence.csv", help="Tabular output path.")
PARSER.add_argument("--repetitions", type=int, default=41, help="Timed repetitions per case (default: 41).")
PARSER.add_argument("--warmups", type=int, default=8, help="Untimed warm-up calls per case (default: 8).")
ARGS = PARSER.parse_args()
if ARGS.repetitions < 3:
    PARSER.error("--repetitions must be at least 3")
if ARGS.warmups < 0:
    PARSER.error("--warmups must be non-negative")

BACKEND = ARGS.backend.resolve()
if not (BACKEND / "tla_parser.py").is_file() or not (BACKEND / "verification.py").is_file():
    PARSER.error(f"--backend must contain tla_parser.py and verification.py: {BACKEND}")
sys.path.insert(0, str(BACKEND))

from tla_parser import compile_tla  # noqa: E402
from verification import verify  # noqa: E402


T = TypeVar("T")


def source_tree_digest(directory: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(directory.glob("*.py")):
        hasher.update(path.name.encode("utf-8") + b"\0")
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def counter_source(maximum: int) -> str:
    return f"""---- MODULE Counter{maximum} ----
VARIABLE count
Init == count = 0
Increment == /\\ count < {maximum}
             /\\ count' = count + 1
Reset == /\\ count = {maximum}
         /\\ count' = 0
Next == Increment \\/ Reset
===="""


def width_source(width: int) -> str:
    """Build a deterministic source family whose front-end work grows by width."""
    names = [f"x{index}" for index in range(width)]
    init_lines = [f"/\\ {name} = 0" for name in names]
    update_lines = ["/\\ x0 < 1", "/\\ x0' = x0 + 1"] + [f"/\\ {name}' = {name}" for name in names[1:]]
    return "\n".join(
        [
            f"---- MODULE Width{width} ----",
            "VARIABLES " + ", ".join(names),
            "Init == " + init_lines[0],
            *["        " + line for line in init_lines[1:]],
            "Step == " + update_lines[0],
            *["        " + line for line in update_lines[1:]],
            "Next == Step",
            "====",
        ]
    )


def timing(function: Callable[[], T]) -> tuple[T, dict[str, float]]:
    """Run warm-ups and return one result plus nanosecond summary statistics."""
    for _ in range(ARGS.warmups):
        function()
    elapsed: list[int] = []
    value: T | None = None
    for _ in range(ARGS.repetitions):
        started = time.perf_counter_ns()
        value = function()
        elapsed.append(time.perf_counter_ns() - started)
    assert value is not None
    return value, {
        "median_ms": statistics.median(elapsed) / 1_000_000,
        "mean_ms": statistics.mean(elapsed) / 1_000_000,
        "minimum_ms": min(elapsed) / 1_000_000,
        "maximum_ms": max(elapsed) / 1_000_000,
        "stdev_ms": statistics.stdev(elapsed) / 1_000_000,
    }


def compiler_measurements() -> list[dict]:
    rows: list[dict] = []
    for width in (1, 5, 10, 20, 40):
        source = width_source(width)
        compilation, stats = timing(lambda source=source: compile_tla(source))
        row = {
            "stage": "compile",
            "case": f"width_{width}",
            "variables": width,
            "source_bytes": len(source.encode("utf-8")),
            "actions": len(compilation.model.actions),
            "generated_python_bytes": len(compilation.python.encode("utf-8")),
            **stats,
        }
        row["source_bytes_per_second"] = row["source_bytes"] / (row["median_ms"] / 1_000)
        rows.append(row)
    return rows


def exploration_measurements() -> list[dict]:
    rows: list[dict] = []
    for maximum in (2, 5, 10, 20, 39):
        source = counter_source(maximum)
        graph, stats = timing(
            lambda source=source: verify(source, "count >= 0", max_depth=40, max_states=500)
        )
        summary = graph["summary"]
        row = {
            "stage": "compile_and_explore",
            "case": f"counter_{maximum}",
            "counter_maximum": maximum,
            "source_bytes": len(source.encode("utf-8")),
            "states": summary["states"],
            "transitions": summary["transitions"],
            "truncated": summary["truncated"],
            **stats,
        }
        row["states_per_second"] = row["states"] / (row["median_ms"] / 1_000)
        rows.append(row)
    return rows


def machine_metadata() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "processor": platform.processor() or "not reported",
        "machine": platform.machine(),
    }


def write_csv(rows: list[dict]) -> None:
    fields = sorted({field for row in rows for field in row})
    with ARGS.csv_output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    compile_rows = compiler_measurements()
    explore_rows = exploration_measurements()
    rows = compile_rows + explore_rows
    output = {
        "scope": "Timed end-to-end restricted compilation and typed-IR breadth-first exploration on one local machine.",
        "not_claimed": "A cross-tool comparison, a general scalability result, full TLA+ support, TLC equivalence, temporal verification, or a semantic-preservation theorem.",
        "protocol": {
            "timer": "time.perf_counter_ns",
            "warmups_per_case": ARGS.warmups,
            "timed_repetitions_per_case": ARGS.repetitions,
            "reported_statistics": ["median_ms", "mean_ms", "minimum_ms", "maximum_ms", "stdev_ms"],
            "isolation": "One local process; no CPU pinning, process priority change, or cross-machine normalisation.",
        },
        "machine": machine_metadata(),
        "source_snapshot_sha256": source_tree_digest(BACKEND),
        "backend_path": str(BACKEND),
        "measurements": {"compilation": compile_rows, "exploration": explore_rows},
    }
    ARGS.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_csv(rows)

    print("Compilation (median ms)")
    for row in compile_rows:
        print(f"  {row['case']:>10}: {row['median_ms']:.4f} ms; {row['source_bytes']} bytes; {row['variables']} variables")
    print("Compilation plus exploration (median ms)")
    for row in explore_rows:
        print(f"  {row['case']:>10}: {row['median_ms']:.4f} ms; {row['states']} states; {row['transitions']} transitions")
    print(f"Wrote {ARGS.output}")
    print(f"Wrote {ARGS.csv_output}")


if __name__ == "__main__":
    main()

