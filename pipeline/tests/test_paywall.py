from __future__ import annotations

import pytest

from wgmesh_pipeline.paywall import detect_component_paywall


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("+if license_check(user) { return nil }", "license check"),
        ("+if trial_expired(account) { return false }", "trial expiry"),
        ("+pause_on_expiry = true", "routing pause on expiry"),
        ("+kill_switch.activate()", "kill switch"),
        ("+return payment_required(feature_gate(account_state))", "pay-to-unlock"),
    ],
)
def test_detect_component_paywall_matches_each_vector(text: str, reason: str) -> None:
    paywall_ok, reasons = detect_component_paywall(text, ["internal/billing.go"])

    assert paywall_ok is False
    assert reason in reasons


def test_detect_component_paywall_searches_spec_content() -> None:
    paywall_ok, reasons = detect_component_paywall(
        "+docs only\n",
        ["docs/billing.md"],
        spec_content="Mesh daemons stop routing if expired.",
    )

    assert paywall_ok is False
    assert reasons == ["routing pause on expiry"]


def test_detect_component_paywall_allows_clean_managed_layer_text() -> None:
    paywall_ok, reasons = detect_component_paywall(
        "+Add cloudroof signup and invoice sync for managed ingress billing.\n",
        ["docs/cloudroof-billing.md"],
        spec_content="Collect invoice contact details; never gate local mesh operation.",
    )

    assert paywall_ok is True
    assert reasons == []
