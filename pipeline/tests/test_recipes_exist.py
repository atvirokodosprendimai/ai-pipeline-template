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
    import yaml
    recipe = yaml.safe_load((RECIPES_DIR / "wgmesh-implementation.yaml").read_text())
    settings = recipe.get("settings", {})
    assert settings.get("goose_provider") == "anthropic"
    # The ACTUAL pinned model (not file text / comments) must EXIST on z.ai —
    # an unlisted id silently no-ops (GLM-4.7 once did). Current listed flagships
    # per z.ai docs 2026-06-14.
    KNOWN_GOOD = {"GLM-5.1", "GLM-5", "glm-4.6"}
    assert settings.get("goose_model") in KNOWN_GOOD
