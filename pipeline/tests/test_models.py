from __future__ import annotations

import pytest

from wgmesh_pipeline.models import (
    ModelProfile,
    credential_for,
    parse_registry,
    parse_stage_routing,
    resolve_profile,
)


_TWO_PROFILE_JSON = """
{
  "spec-cheap":   {"provider": "anthropic",  "model": "GLM-4.7",      "billing": "native",     "credential_env": "ZAI_API_KEY", "host": "https://api.z.ai/api/anthropic"},
  "impl-capable": {"provider": "openrouter", "model": "deepseek/v3",  "billing": "openrouter", "credential_env": "OPENROUTER_API_KEY"}
}
"""


def test_parse_registry_two_profiles() -> None:
    registry = parse_registry(_TWO_PROFILE_JSON)
    assert set(registry) == {"spec-cheap", "impl-capable"}
    assert registry["spec-cheap"].provider == "anthropic"
    assert registry["spec-cheap"].host == "https://api.z.ai/api/anthropic"
    assert registry["impl-capable"].billing == "openrouter"
    assert registry["impl-capable"].host is None
    # the map key becomes the profile key
    assert registry["impl-capable"].key == "impl-capable"


def test_parse_stage_routing_maps_stage_to_key() -> None:
    routing = parse_stage_routing('{"spec": "spec-cheap", "implement": "impl-capable"}')
    assert routing == {"spec": "spec-cheap", "implement": "impl-capable"}


def test_resolve_profile_by_stage() -> None:
    registry = parse_registry(_TWO_PROFILE_JSON)
    routing = parse_stage_routing('{"spec": "spec-cheap", "implement": "impl-capable"}')
    assert resolve_profile(registry, routing, "spec").key == "spec-cheap"
    assert resolve_profile(registry, routing, "implement").key == "impl-capable"


def test_resolve_profile_falls_back_to_registry_default() -> None:
    registry = {
        "default": ModelProfile(
            key="default",
            provider="anthropic",
            model="GLM-4.7",
            billing="native",
            credential_env="ZAI_API_KEY",
            host="https://api.z.ai/api/anthropic",
        )
    }
    # no routing entry for this stage, but a 'default' profile exists
    assert resolve_profile(registry, {}, "implement").key == "default"


def test_resolve_profile_unmapped_stage_no_default_raises() -> None:
    registry = parse_registry(_TWO_PROFILE_JSON)
    routing = parse_stage_routing('{"spec": "spec-cheap"}')
    with pytest.raises(ValueError, match="no model route for stage 'implement'"):
        resolve_profile(registry, routing, "implement")


def test_resolve_profile_route_to_missing_key_raises() -> None:
    registry = parse_registry(_TWO_PROFILE_JSON)
    routing = parse_stage_routing('{"implement": "does-not-exist"}')
    with pytest.raises(ValueError, match="not in the registry"):
        resolve_profile(registry, routing, "implement")


def test_malformed_registry_json_names_the_var() -> None:
    with pytest.raises(ValueError, match="MODEL_REGISTRY must be valid JSON"):
        parse_registry("{not json")


def test_registry_rejects_bad_billing() -> None:
    with pytest.raises(ValueError, match="billing must be one of"):
        parse_registry(
            '{"x": {"provider": "p", "model": "m", "billing": "flat", "credential_env": "K"}}'
        )


def test_registry_rejects_missing_required_field() -> None:
    with pytest.raises(ValueError, match="missing required fields"):
        parse_registry('{"x": {"provider": "p", "model": "m", "billing": "native"}}')


def test_registry_rejects_unknown_field() -> None:
    with pytest.raises(ValueError, match="unknown fields"):
        parse_registry(
            '{"x": {"provider": "p", "model": "m", "billing": "native", "credential_env": "K", "temp": 1}}'
        )


def test_credential_for_reads_value() -> None:
    profile = parse_registry(_TWO_PROFILE_JSON)["impl-capable"]
    assert credential_for(profile, {"OPENROUTER_API_KEY": "or-key"}) == "or-key"


def test_credential_for_missing_var_raises() -> None:
    profile = parse_registry(_TWO_PROFILE_JSON)["impl-capable"]
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY, which is unset"):
        credential_for(profile, {"PATH": "/usr/bin"})


def test_empty_inputs_yield_empty_collections() -> None:
    assert parse_registry(None) == {}
    assert parse_registry("   ") == {}
    assert parse_stage_routing(None) == {}
