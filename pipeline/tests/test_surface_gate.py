"""U1/U2/U4 — surface gate logic (graph/nodes/surface_gate.py).

Pure resolution + decision + the node's label disposition. Graph-integration
(both-impl wiring) is covered in the parity tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from wgmesh_pipeline.github.client import GitHubIssue
from wgmesh_pipeline.graph.nodes.surface_gate import (
    decide_surface_gate,
    resolve_issue_surface,
    run_surface_gate,
    surface_gate_blocks,
)


def _issue(number=783, title="Add widget", labels=(), body=""):
    return GitHubIssue(number=number, title=title, labels=tuple(labels), state="open", body=body) \
        if "body" in GitHubIssue.__dataclass_fields__ \
        else GitHubIssue(number=number, title=title, labels=tuple(labels), state="open")


@dataclass
class FakeForge:
    calls: list = field(default_factory=list)

    def add_label(self, issue_number: int, label: str) -> None:
        self.calls.append((issue_number, label))


# ---- U1: resolve_issue_surface --------------------------------------------

def test_resolve_reads_service_label_no_classifier_call() -> None:
    called = []
    res = resolve_issue_surface(
        _issue(labels=("surface:service", "fn:dev")),
        classifier_fn=lambda t, b: called.append(1) or ("product", 1.0),
    )
    assert (res.surface, res.source) == ("service", "label")
    assert called == []  # labelled → classifier never runs


def test_resolve_reads_product_label() -> None:
    res = resolve_issue_surface(_issue(labels=("surface:product",)))
    assert (res.surface, res.source) == ("product", "label")


def test_resolve_classifies_unlabelled_service() -> None:
    res = resolve_issue_surface(_issue(labels=("fn:dev",)), classifier_fn=lambda t, b: ("service", 0.9))
    assert (res.surface, res.source) == ("service", "classified")


def test_resolve_classifies_unlabelled_product() -> None:
    res = resolve_issue_surface(_issue(labels=()), classifier_fn=lambda t, b: ("product", 0.8))
    assert (res.surface, res.source) == ("product", "classified")


def test_resolve_no_classifier_is_unknown_never_product() -> None:
    res = resolve_issue_surface(_issue(labels=("fn:dev",)), classifier_fn=None)
    assert (res.surface, res.source) == ("unknown", "none")


def test_resolve_classifier_failure_is_unknown_not_product() -> None:
    def boom(t, b):
        raise RuntimeError("provider down")
    res = resolve_issue_surface(_issue(), classifier_fn=boom)
    assert res.surface == "unknown"


def test_resolve_invalid_classifier_output_is_unknown() -> None:
    res = resolve_issue_surface(_issue(), classifier_fn=lambda t, b: ("banana", 0.99))
    assert res.surface == "unknown"


def test_resolve_both_surface_labels_service_wins() -> None:
    res = resolve_issue_surface(_issue(labels=("surface:product", "surface:service")))
    assert res.surface == "service"  # mirrors _resolve_surface precedence


# ---- U2: decide_surface_gate ----------------------------------------------

def test_decide_product_label_builds() -> None:
    from wgmesh_pipeline.graph.nodes.surface_gate import SurfaceResolution
    assert decide_surface_gate(SurfaceResolution("product", 1.0, "label")) == "build"


def test_decide_service_blocks() -> None:
    from wgmesh_pipeline.graph.nodes.surface_gate import SurfaceResolution
    assert decide_surface_gate(SurfaceResolution("service", 1.0, "label")) == "block_service"
    assert decide_surface_gate(SurfaceResolution("service", 0.6, "classified")) == "block_service"


def test_decide_unknown_blocks() -> None:
    from wgmesh_pipeline.graph.nodes.surface_gate import SurfaceResolution
    assert decide_surface_gate(SurfaceResolution("unknown", 0.0, "none")) == "block_unknown"


def test_decide_low_confidence_product_blocks() -> None:
    from wgmesh_pipeline.graph.nodes.surface_gate import SurfaceResolution
    assert decide_surface_gate(SurfaceResolution("product", 0.3, "classified")) == "block_unknown"


# ---- run_surface_gate node + U4 contract conformance ----------------------

def test_node_product_label_builds_no_writes() -> None:
    forge = FakeForge()
    out = run_surface_gate({"issue": _issue(labels=("surface:product",)), "github": forge})
    assert out["surface_verdict"] == "build"
    assert surface_gate_blocks(out) is False
    assert forge.calls == []  # no label churn for an already-labelled product issue


def test_node_service_label_blocks() -> None:
    forge = FakeForge()
    out = run_surface_gate({"issue": _issue(labels=("surface:service",)), "github": forge})
    assert out["surface_verdict"] == "block_service"
    assert surface_gate_blocks(out) is True


def test_node_classified_service_persists_label() -> None:
    # U4 contract: a classified service issue ends with surface:service present
    # (+ needs-human from the escalate wiring) → gtm-decision stream.
    forge = FakeForge()
    out = run_surface_gate({
        "issue": _issue(labels=("fn:dev",)),
        "github": forge,
        "surface_classifier": lambda t, b: ("service", 0.9),
    })
    assert out["surface_verdict"] == "block_service"
    assert (783, "surface:service") in forge.calls  # persisted for the contract


def test_node_unknown_no_classifier_blocks_no_surface_label() -> None:
    # U4 contract fail-safe: needs-human with NO surface → product-decision.
    forge = FakeForge()
    out = run_surface_gate({"issue": _issue(labels=("fn:dev",)), "github": forge})
    assert out["surface_verdict"] == "block_unknown"
    assert forge.calls == []  # no surface label applied → product-decision fail-safe


def test_node_classified_product_persists_and_builds() -> None:
    forge = FakeForge()
    out = run_surface_gate({
        "issue": _issue(labels=()),
        "github": forge,
        "surface_classifier": lambda t, b: ("product", 0.8),
    })
    assert out["surface_verdict"] == "build"
    assert (783, "surface:product") in forge.calls


# ---- U3: surface-gate inversion (cloudroof instance, surface_home=service) ----

from dataclasses import dataclass as _dc  # noqa: E402


@_dc
class _Cfg:
    """Minimal stand-in for Config — only ``surface_home`` is read by the node."""
    surface_home: str = "product"


def test_decide_inverted_service_home_builds_service_blocks_product() -> None:
    from wgmesh_pipeline.graph.nodes.surface_gate import SurfaceResolution
    d = lambda res: decide_surface_gate(res, "service")
    assert d(SurfaceResolution("service", 1.0, "label")) == "build"
    assert d(SurfaceResolution("service", 0.9, "classified")) == "build"
    assert d(SurfaceResolution("product", 1.0, "label")) == "block_product"
    assert d(SurfaceResolution("product", 0.8, "classified")) == "block_product"
    assert d(SurfaceResolution("unknown", 0.0, "none")) == "block_unknown"
    # low-confidence home (service) guess fails safe, never builds
    assert d(SurfaceResolution("service", 0.3, "classified")) == "block_unknown"


def test_decide_default_surface_home_is_product_unchanged() -> None:
    # Explicit guard that the default arg keeps the wgmesh path identical.
    from wgmesh_pipeline.graph.nodes.surface_gate import SurfaceResolution
    assert decide_surface_gate(SurfaceResolution("product", 1.0, "label")) == "build"
    assert decide_surface_gate(SurfaceResolution("service", 1.0, "label")) == "block_service"


def test_node_service_home_builds_service_label() -> None:
    forge = FakeForge()
    out = run_surface_gate({
        "issue": _issue(labels=("surface:service",)),
        "github": forge,
        "config": _Cfg(surface_home="service"),
    })
    assert out["surface_verdict"] == "build"
    assert surface_gate_blocks(out) is False


def test_node_service_home_blocks_product_label() -> None:
    forge = FakeForge()
    out = run_surface_gate({
        "issue": _issue(labels=("surface:product",)),
        "github": forge,
        "config": _Cfg(surface_home="service"),
    })
    assert out["surface_verdict"] == "block_product"
    assert surface_gate_blocks(out) is True


def test_node_default_config_absent_is_product_home() -> None:
    # No config in state → product home (default); service still blocked.
    forge = FakeForge()
    out = run_surface_gate({"issue": _issue(labels=("surface:service",)), "github": forge})
    assert out["surface_verdict"] == "block_service"
