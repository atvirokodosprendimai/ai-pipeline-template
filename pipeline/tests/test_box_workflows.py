"""U4 — characterization of the box-instance workflows + the cloudroof unit.

These workflows are load-bearing infra with no app-behavior to unit-test, so the
guard is: (1) every touched workflow stays valid YAML, (2) the wgmesh path is
byte-unchanged when ``service`` defaults — the resolve steps map ``wgmesh`` to the
original unit/env-file, (3) the destructive ``provision-pipeline-box`` is NOT
parameterized (a co-resident 2nd instance must never recreate the shared box),
(4) the new cloudroof unit + installer wire the service surface correctly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_WF = _ROOT / ".github" / "workflows"
_UNIT = _ROOT / "pipeline" / "deploy" / "cloudroof-pipeline.service"


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _load(name: str) -> dict:
    return yaml.safe_load(_text(_WF / name))


def _inputs(wf: dict) -> dict:
    # YAML 1.1 parses the bare `on:` key as boolean True (the "Norway problem").
    on = wf.get("on", wf.get(True, {})) or {}
    dispatch = on.get("workflow_dispatch") or {}
    return dispatch.get("inputs") or {}


@pytest.mark.parametrize(
    "name",
    [
        "set-box-env.yml",
        "update-pipeline-box.yml",
        "install-cloudroof-instance.yml",
        "provision-pipeline-box.yml",
    ],
)
def test_workflow_is_valid_yaml(name: str) -> None:
    assert isinstance(_load(name), dict)


def test_cloudroof_unit_parses_and_targets_service_surface() -> None:
    txt = _text(_UNIT)
    for section in ("[Unit]", "[Service]", "[Install]"):
        assert section in txt
    # Distinct env file (never shares the wgmesh instance's state)…
    assert "EnvironmentFile=/etc/cloudroof-pipeline/env" in txt
    # …but shares the wgmesh code install + venv (KTD1, 2nd instance not refactor).
    assert "ExecStart=/opt/wgmesh-pipeline/.venv/bin/python -m wgmesh_pipeline.main" in txt
    # cloudroof working tree must be writable for goose specs/commits.
    assert "/opt/cloudroof-checkout" in txt
    assert "ReadWritePaths=/opt/wgmesh-pipeline /opt/cloudroof-checkout" in txt


# ---- set-box-env + update: service input, default wgmesh unchanged -----------

@pytest.mark.parametrize("name", ["set-box-env.yml", "update-pipeline-box.yml"])
def test_service_input_defaults_wgmesh(name: str) -> None:
    inputs = _inputs(_load(name))
    assert "service" in inputs
    assert inputs["service"]["default"] == "wgmesh"


@pytest.mark.parametrize("name", ["set-box-env.yml", "update-pipeline-box.yml"])
def test_resolve_step_maps_both_units(name: str) -> None:
    txt = _text(_WF / name)
    # The default-wgmesh path resolves to the original unit (byte-unchanged behavior)…
    assert "UNIT=wgmesh-pipeline" in txt
    # …and cloudroof resolves to the 2nd unit. Unknown values fail closed.
    assert "UNIT=cloudroof-pipeline" in txt
    assert "expected wgmesh|cloudroof" in txt


def test_set_box_env_threads_env_file_per_instance() -> None:
    txt = _text(_WF / "set-box-env.yml")
    assert "ENV_FILE=/etc/wgmesh-pipeline/env" in txt
    assert "ENV_FILE=/etc/cloudroof-pipeline/env" in txt
    # The remote script must use the resolved unit/env-file, not a hardcoded one.
    assert 'systemctl restart "$UNIT"' in txt


def test_update_box_reuses_workflow_call_default_wgmesh() -> None:
    # Auto-Deploy-on-Merge calls this reusably with no service → must stay wgmesh.
    wf = _load("update-pipeline-box.yml")
    on = wf.get("on", wf.get(True, {})) or {}
    call_inputs = (on.get("workflow_call") or {}).get("inputs") or {}
    assert call_inputs["service"]["default"] == "wgmesh"


# ---- provision stays destructive-but-unparameterized (no co-resident footgun) -

def test_provision_box_is_not_parameterized_for_service() -> None:
    # Recreating the shared box to add cloudroof would kill the wgmesh instance —
    # the 2nd instance is installed non-destructively via install-cloudroof-instance.
    assert "service" not in _inputs(_load("provision-pipeline-box.yml"))


# ---- installer wires the service surface ------------------------------------

def test_installer_writes_cloudroof_env_and_enables_unit() -> None:
    txt = _text(_WF / "install-cloudroof-instance.yml")
    assert "TARGET_REPO=atvirokodosprendimai/cloudroof-eu" in txt
    assert "SURFACE_HOME=service" in txt
    assert "WGMESH_CHECKOUT_PATH=/opt/cloudroof-checkout" in txt
    assert "install -m 0644 /opt/wgmesh-pipeline/pipeline/deploy/cloudroof-pipeline.service" in txt
    assert "systemctl enable --now cloudroof-pipeline" in txt
    # Non-destructive: never creates/deletes a server.
    assert "hcloud server create" not in txt
    assert "hcloud server delete" not in txt
