from __future__ import annotations

from wgmesh_pipeline.graph.state import Classification, GraphState


def triage_node(state: GraphState) -> GraphState:
    next_state = dict(state)
    _visit(next_state, "triage")
    override = next_state.get("classification_override")
    if override:
        next_state["classification"] = override
        return next_state

    title = next_state["issue"].title.lower()
    if "wont" in title or "won't" in title:
        classification: Classification = "wont-do"
    elif "question" in title or "needs info" in title:
        classification = "needs-info"
    elif "feature" in title:
        classification = "feature"
    else:
        classification = "fix"
    next_state["classification"] = classification
    return next_state


def _visit(state: dict, node: str) -> None:
    state.setdefault("visited", []).append(node)

