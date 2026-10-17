"""Bounded breadth-first exploration for the documented restricted TLA+ fragment."""
from __future__ import annotations

from collections import deque

from tla_parser import (
    TranslationError,
    canonical_state_key,
    evaluate_expression,
    expression_type,
    parse_expression,
    parse_tla,
    successors,
)


ENGINE_NAME = "typed_ir_breadth_first_explicit_state_explorer"


def _check_limits(max_depth: int, max_states: int) -> None:
    if type(max_depth) is not int or not 0 <= max_depth <= 40:
        raise TranslationError("max_depth must be an integer from 0 to 40.")
    if type(max_states) is not int or not 1 <= max_states <= 500:
        raise TranslationError("max_states must be an integer from 1 to 500.")


def verify(source: str, property_text: str = "", max_depth: int = 12, max_states: int = 120) -> dict:
    """Explore a typed model IR without executing the generated Python rendering.

    A finite pass means that the reachable graph of this restricted model was
    exhausted before a cutoff. A bounded pass means that a configured depth or
    state limit stopped the breadth-first search.
    """
    _check_limits(max_depth, max_states)
    model = parse_tla(source)
    property_source = property_text.strip()
    property_expression = parse_expression(property_source, model.variable_types) if property_source else None
    if property_expression is not None:
        # parse_expression has type-checked the tree. This explicit check makes
        # the contract local to the verifier as well.
        if expression_type(property_expression, model.variable_types) != "bool":
            raise TranslationError("The property must be a Boolean state predicate.")

    initial = dict(model.initial_state)
    nodes = [{"id": 0, "state": initial, "depth": 0}]
    edges: list[dict] = []
    visited = {canonical_state_key(model, initial): 0}
    parent: dict[int, int | None] = {0: None}
    queue = deque([0])
    cutoff = False
    violations: list[int] = []
    deadlocks: list[int] = []

    while queue:
        node_id = queue.popleft()
        node = nodes[node_id]
        state = node["state"]
        if property_expression is not None and not evaluate_expression(property_expression, state):
            violations.append(node_id)

        outgoing = successors(model, state)
        if node["depth"] >= max_depth:
            if outgoing:
                cutoff = True
            else:
                deadlocks.append(node_id)
            continue
        if not outgoing:
            deadlocks.append(node_id)

        for action_name, successor in outgoing:
            identity = canonical_state_key(model, successor)
            if identity not in visited:
                if len(nodes) >= max_states:
                    cutoff = True
                    continue
                target_id = len(nodes)
                visited[identity] = target_id
                parent[target_id] = node_id
                nodes.append({"id": target_id, "state": successor, "depth": node["depth"] + 1})
                queue.append(target_id)
            else:
                target_id = visited[identity]
            edges.append({"source": node_id, "target": target_id, "action": action_name})

    def trace(target_id: int) -> list[int]:
        route: list[int] = []
        current: int | None = target_id
        while current is not None:
            route.append(current)
            current = parent[current]
        return list(reversed(route))

    property_status = (
        "not_checked"
        if not property_source
        else "violation"
        if violations
        else "bounded_pass"
        if cutoff
        else "pass_finite_graph"
    )
    return {
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "engine": ENGINE_NAME,
            "states": len(nodes),
            "transitions": len(edges),
            "max_depth": max_depth,
            "max_states": max_states,
            "truncated": cutoff,
            "deadlocks": len(deadlocks),
            "property": property_source,
            "property_status": property_status,
        },
        "counterexample": trace(violations[0]) if violations else [],
        "deadlock_trace": trace(deadlocks[0]) if deadlocks else [],
        "disclaimer": (
            "Breadth-first explicit-state exploration of a typed restricted TLA+ fragment. "
            "It is not TLC, SAT/SMT bounded model checking, temporal verification, or a refinement proof."
        ),
    }
