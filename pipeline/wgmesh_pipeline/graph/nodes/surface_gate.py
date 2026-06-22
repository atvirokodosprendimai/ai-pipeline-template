"""Surface gate — build only this instance's *home* surface; park everything else.

Runs on the triage→spec seam (both graph impls). It resolves the issue's surface
(reading the ``surface:*`` label, else classifying title+body via an injected
LLM callable), then decides against the instance's ``surface_home`` (``product``
for the wgmesh instance, ``service`` for the cloudroof instance — KTD2):

  - home surface (confident)     → ``build``          (the only path to spec→impl)
  - a known, off-home surface    → ``block_<surface>`` (park; built by the OTHER instance)
  - unknown / low-confidence     → ``block_unknown``   (fail-safe: park, never build)

The default ``surface_home`` is ``product`` so the wgmesh instance is byte-unchanged:
``product`` builds, ``service`` → ``block_service``, unknown → ``block_unknown``. The
cloudroof instance sets ``surface_home=service`` (via ``Config.surface_home`` / the
``SURFACE_HOME`` env), inverting the gate: ``service`` builds, ``product`` →
``block_product``.

Blocked issues are parked via labels: a classified surface is persisted, and the
block path (the graph's existing ``escalate``) adds ``needs-human``. Those labels
ARE the Quackback decision-stream input — ``surface:service`` + ``needs-human`` →
``gtm-decision``; ``needs-human`` with no surface → ``product-decision`` fail-safe
(see ``docs/quackback-decision-streams.md``). No separate emit.

Reuses ``observation._resolve_surface`` and the surface label constants (R5).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from wgmesh_pipeline.graph.state import GraphState
from wgmesh_pipeline.observation import _resolve_surface

log = logging.getLogger("wgmesh_pipeline.surface_gate")

# Below this, a classifier verdict is not trusted enough to build on — fail safe
# to block_unknown rather than spec→impl a shaky guess.
MIN_CONFIDENCE = 0.5

# Which surface THIS pipeline instance builds. Mirrors ``Config.surface_home``;
# the literal default keeps this module decoupled from config (no import cycle).
DEFAULT_SURFACE_HOME = "product"

# (title, body) -> (surface, confidence). Injected so tests and the graph wire a
# real LLM classifier without this module importing a model client.
SurfaceClassifier = Callable[[str, str], "tuple[str, float]"]


@dataclass(frozen=True)
class SurfaceResolution:
    surface: str  # "product" | "service" | "unknown"
    confidence: float
    source: str  # "label" | "classified" | "none"


def resolve_issue_surface(
    issue: Any, *, classifier_fn: SurfaceClassifier | None = None
) -> SurfaceResolution:
    """Resolve an issue's surface from its labels, classifying title+body when no
    ``surface:*`` label is present. Never silently assumes product: an absent
    label with no classifier, or a failed/invalid classification, is ``unknown``."""
    labels = tuple(getattr(issue, "labels", ()) or ())
    labeled = _resolve_surface(labels)
    if labeled is not None:
        return SurfaceResolution(labeled, 1.0, "label")
    if classifier_fn is None:
        return SurfaceResolution("unknown", 0.0, "none")
    try:
        surface, confidence = classifier_fn(
            getattr(issue, "title", "") or "", getattr(issue, "body", "") or ""
        )
    except Exception:  # noqa: BLE001 — a classifier failure must fail safe, never build
        log.warning("surface classifier failed for #%s; treating as unknown", getattr(issue, "number", "?"))
        return SurfaceResolution("unknown", 0.0, "classified")
    if surface not in ("product", "service"):
        return SurfaceResolution("unknown", float(confidence), "classified")
    return SurfaceResolution(surface, float(confidence), "classified")


def decide_surface_gate(
    resolution: SurfaceResolution, surface_home: str = DEFAULT_SURFACE_HOME
) -> str:
    """Map a resolved surface to a gate verdict against ``surface_home``:
    ``build`` | ``block_<surface>`` | ``block_unknown``. Policy (confidence
    gating) lives here, not in resolution.

    The home surface builds only when confident (a low-confidence classified
    guess at the home surface fails safe to ``block_unknown``). A confident,
    known off-home surface is parked under its own ``block_<surface>`` verdict so
    the OTHER instance can claim it. Everything else (unknown) parks unknown."""
    if resolution.surface == surface_home and resolution.confidence >= MIN_CONFIDENCE:
        return "build"
    if resolution.surface in ("product", "service") and resolution.surface != surface_home:
        return f"block_{resolution.surface}"
    return "block_unknown"


def run_surface_gate(state: GraphState) -> GraphState:
    """Graph node: resolve + decide, persist a classified surface label, and
    record the verdict in state. Does NOT itself escalate — the graph wiring maps
    a non-``build`` verdict to the existing ``escalate`` path (which adds
    ``needs-human``), so both graph impls share one disposition."""
    next_state = dict(state)
    next_state.setdefault("visited", []).append("surface_gate")
    issue = next_state["issue"]
    classifier = next_state.get("surface_classifier")
    # This instance's home surface (Config.surface_home); default product so the
    # wgmesh instance — and the existing node tests that pass no config — keep the
    # original product-builds/service-blocks behavior.
    cfg = next_state.get("config")
    surface_home = getattr(cfg, "surface_home", DEFAULT_SURFACE_HOME)
    resolution = resolve_issue_surface(issue, classifier_fn=classifier)
    verdict = decide_surface_gate(resolution, surface_home)
    next_state["surface"] = resolution.surface
    next_state["surface_verdict"] = verdict

    forge = next_state.get("github")
    # Persist a classified surface so the decision is idempotent and visible to
    # the decision-stream contract (a labelled issue routes deterministically).
    if (
        resolution.source == "classified"
        and resolution.surface in ("product", "service")
        and forge is not None
    ):
        forge.add_label(issue.number, f"surface:{resolution.surface}")
        # block_service via classification: surface:service is now present, so a
        # service issue ends with surface:service + needs-human → gtm-decision.

    if verdict == "block_unknown":
        # Contract fail-safe: needs-human with no surface → product-decision
        # stream. Log so the upstream classifier can be corrected.
        log.warning(
            "surface-gate: issue #%s has no resolvable surface — blocking spec→impl "
            "and parking to needs-human (product-decision fail-safe)",
            getattr(issue, "number", "?"),
        )

    return next_state


def surface_gate_blocks(state: GraphState) -> bool:
    """True when the gate's verdict is anything but ``build`` (used by the legacy
    invoke path to mirror the wont-do/needs-info escape)."""
    return state.get("surface_verdict") != "build"
