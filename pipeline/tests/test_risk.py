from __future__ import annotations

from wgmesh_pipeline.risk import classify_risk


def test_docs_only_diff_is_low_risk() -> None:
    result = classify_risk(["docs/readme.md"], "+Clarify install steps\n", max_files=3)

    assert result.tier == "low"
    assert result.reasons == ()


def test_crypto_path_is_high_risk() -> None:
    result = classify_risk(["internal/crypto/key.go"], "+return key\n", max_files=3)

    assert result.tier == "high"
    assert "high-risk path" in result.reasons[0]


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

