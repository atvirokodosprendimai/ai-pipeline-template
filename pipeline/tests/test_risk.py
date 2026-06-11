from __future__ import annotations

import pytest

from wgmesh_pipeline import secret_scan as secret_scan_mod
from wgmesh_pipeline.secret_scan import SecretScanResult
from wgmesh_pipeline.risk import classify_risk


@pytest.fixture(autouse=True)
def _no_real_ggshield(monkeypatch):
    # Tests that don't inject a scanner must not spawn a real ggshield
    # subprocess. risk.classify_risk does a call-time import from
    # wgmesh_pipeline.secret_scan, so patch the source attribute. Default to
    # "clean scan available"; tests exercising keyword fallback or a found
    # secret inject their own scanner explicitly.
    monkeypatch.setattr(
        secret_scan_mod,
        "scan_diff_for_secrets",
        lambda diff_text: SecretScanResult(available=True, found=False, detail="ggshield: 0 incident(s)"),
    )


def test_docs_only_diff_is_low_risk() -> None:
    result = classify_risk(["docs/readme.md"], "+Clarify install steps\n", max_files=3)

    assert result.tier == "low"
    assert result.reasons == ()


def test_crypto_path_is_high_risk() -> None:
    result = classify_risk(["internal/crypto/key.go"], "+return key\n", max_files=3)

    assert result.tier == "high"
    assert "high-risk path" in result.reasons[0]


def test_secret_key_added_in_benign_path_is_high_risk() -> None:
    diff = """diff --git a/config/example.env b/config/example.env
++ b/config/example.env
+SECRET_KEY=abc123
"""

    result = classify_risk(
        ["config/example.env"],
        diff,
        max_files=3,
        secret_scanner=lambda diff_text: SecretScanResult(
            available=False,
            found=False,
            detail="ggshield not installed",
        ),
    )

    assert result.tier == "high"
    assert "high-risk diff content" in result.reasons[0]


def test_more_than_max_files_is_high_risk() -> None:
    result = classify_risk(["a", "b", "c", "d"], "+small\n", max_files=3)

    assert result.high is True
    assert "exceeds MAX_FILES=3" in result.reasons[0]


def test_added_external_network_call_is_high_risk() -> None:
    diff = """diff --git a/main.go b/main.go
+resp, err := http.Post("https://api.example.com", "application/json", body)
"""

    result = classify_risk(["internal/client.go"], diff, max_files=3)

    assert result.tier == "high"
    assert "network call" in result.reasons[0]


def test_exactly_max_files_boundary_is_low_risk() -> None:
    result = classify_risk(["a", "b", "c"], "+small\n", max_files=3)

    assert result.tier == "low"


def test_clean_diff_with_secret_keyword_not_flagged_when_ggshield_clean() -> None:
    diff = """diff --git a/tests/example.sh b/tests/example.sh
+ b/tests/example.sh
+ ./tool --secret testSecret
"""

    result = classify_risk(
        ["tests/example.sh"],
        diff,
        max_files=3,
        secret_scanner=lambda diff_text: SecretScanResult(available=True, found=False, detail=None),
    )

    assert result.tier == "low"
    assert not any("high-risk diff content" in reason for reason in result.reasons)


def test_verified_secret_flagged() -> None:
    result = classify_risk(
        ["config/example.env"],
        "+PASSWORD=abc123\n",
        max_files=3,
        secret_scanner=lambda diff_text: SecretScanResult(
            available=True,
            found=True,
            detail="ggshield: 1 incident(s) [HardcodedPassword]",
        ),
    )

    assert result.tier == "high"
    assert any("verified secret in diff" in reason for reason in result.reasons)


def test_ggshield_unavailable_falls_back_to_keyword() -> None:
    result = classify_risk(
        ["tests/example.sh"],
        "+./tool --secret testSecret\n",
        max_files=3,
        secret_scanner=lambda diff_text: SecretScanResult(
            available=False,
            found=False,
            detail="ggshield not installed",
        ),
    )

    assert result.tier == "high"
    assert any("keyword fallback" in reason for reason in result.reasons)
