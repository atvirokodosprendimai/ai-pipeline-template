from __future__ import annotations

import re
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
RECIPES_DIR = PIPELINE_ROOT / "recipes"
NODES_DIR = PIPELINE_ROOT / "wgmesh_pipeline" / "graph" / "nodes"

# Wall: live mode shipped referencing wgmesh-implementation.yaml while only
# wgmesh-triage-spec.yaml existed — every implement attempt died 'goose exited
# 1' and node tests (fake runners) never noticed. Any recipe a node names must
# exist on disk, and its prompt must template every param the node passes.


def _referenced_recipes() -> dict[str, Path]:
    refs: dict[str, Path] = {}
    for node_file in NODES_DIR.glob("*.py"):
        for match in re.findall(r"[\"']([\w-]+\.yaml)[\"']", node_file.read_text()):
            refs[match] = node_file
    return refs


def test_every_node_referenced_recipe_exists() -> None:
    refs = _referenced_recipes()
    assert refs, "no recipe references found — extraction regex broke"
    missing = {name: str(src) for name, src in refs.items() if not (RECIPES_DIR / name).exists()}
    assert not missing, f"recipes referenced by nodes but absent from {RECIPES_DIR}: {missing}"


def test_implementation_recipe_declares_node_params() -> None:
    text = (RECIPES_DIR / "wgmesh-implementation.yaml").read_text()
    for param in ("spec_file", "diff_file"):
        assert f"key: {param}" in text
        assert "{{ " + param + " }}" in text


def test_implementation_recipe_pins_known_good_model() -> None:
    # Parse the ACTUAL setting lines (skip comments) — no yaml dep (CI is bare).
    lines = [
        l.strip() for l in (RECIPES_DIR / "wgmesh-implementation.yaml").read_text().splitlines()
        if l.strip() and not l.lstrip().startswith("#")
    ]
    provider = next((l.split(":", 1)[1].strip().strip(chr(34)) for l in lines if l.startswith("goose_provider:")), None)
    model = next((l.split(":", 1)[1].strip().strip(chr(34)) for l in lines if l.startswith("goose_model:")), None)
    assert provider == "anthropic"
    # Pinned model must be one z.ai actually serves — an unserved id silently
    # routes/no-ops. Verified 2026-06-14: requesting GLM-5.x serves glm-5.2.
    assert model in {"GLM-5.2", "GLM-5.1", "GLM-5", "glm-4.6"}
