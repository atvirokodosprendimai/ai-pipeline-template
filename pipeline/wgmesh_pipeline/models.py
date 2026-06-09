"""Model registry and per-stage routing (price/performance #2).

Turns the pipeline's single hardcoded model into a registry of model *profiles*
plus a static stage->model map. Each LLM-invoking stage (spec, implement)
resolves its own profile, so cheap stages run cheap models and capability-
critical stages run capable ones — every choice attributable in Langfuse.

This module is intentionally standalone (no config import) to avoid a circular
dependency: config.py builds Config from these primitives, not the reverse.

Fail-closed throughout (mailservice lesson, inverted for the explicit default):
a misconfigured registry/route raises; it never silently routes to the wrong
model. The ONE allowed implicit default is the zero-config fallback that
config.load_config synthesizes when no registry is configured (R7).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping


VALID_BILLING = frozenset({"native", "openrouter"})


@dataclass(frozen=True)
class ModelProfile:
    """One routable model. The unit of routing.

    ``credential_env`` names the env var holding this model's API key — the
    value is read at Goose-env-build time, never stored here, so secrets stay
    out of the registry JSON and out of this object.
    """

    key: str
    provider: str  # goose provider id: anthropic | openrouter | ...
    model: str  # goose model id / openrouter slug
    billing: str  # "native" | "openrouter"
    credential_env: str  # env var name holding this model's key
    host: str | None = None  # endpoint for native non-default (z.ai, minimax)

    def __post_init__(self) -> None:
        if self.billing not in VALID_BILLING:
            valid = ", ".join(sorted(VALID_BILLING))
            raise ValueError(
                f"model profile {self.key!r}: billing must be one of {valid}; got {self.billing!r}"
            )
        if not self.provider:
            raise ValueError(f"model profile {self.key!r}: provider is required")
        if not self.model:
            raise ValueError(f"model profile {self.key!r}: model is required")
        if not self.credential_env:
            raise ValueError(f"model profile {self.key!r}: credential_env is required")


_PROFILE_FIELDS = frozenset({"provider", "model", "billing", "credential_env", "host"})


def parse_registry(raw: str | None) -> dict[str, ModelProfile]:
    """Parse the ``MODEL_REGISTRY`` env JSON into ``{key: ModelProfile}``.

    Shape: ``{"<key>": {"provider": ..., "model": ..., "billing": ...,
    "credential_env": ..., "host": <optional>}}``. The map key becomes the
    profile key. Empty/None input → empty registry (zero-config path handled by
    the caller).
    """
    if raw is None or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"MODEL_REGISTRY must be valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("MODEL_REGISTRY must be a JSON object of {key: profile}")

    registry: dict[str, ModelProfile] = {}
    for key, spec in data.items():
        if not isinstance(spec, dict):
            raise ValueError(f"MODEL_REGISTRY[{key!r}] must be a JSON object")
        unknown = set(spec) - _PROFILE_FIELDS
        if unknown:
            raise ValueError(
                f"MODEL_REGISTRY[{key!r}] has unknown fields: {', '.join(sorted(unknown))}"
            )
        missing = {"provider", "model", "billing", "credential_env"} - set(spec)
        if missing:
            raise ValueError(
                f"MODEL_REGISTRY[{key!r}] missing required fields: {', '.join(sorted(missing))}"
            )
        registry[key] = ModelProfile(
            key=key,
            provider=spec["provider"],
            model=spec["model"],
            billing=spec["billing"],
            credential_env=spec["credential_env"],
            host=spec.get("host"),
        )
    return registry


StageRouting = Mapping[str, tuple[str, ...]]


def parse_stage_routing(raw: str | None) -> dict[str, tuple[str, ...]]:
    """Parse ``STAGE_ROUTING`` into ``{stage: (registry_key, ...)}``.

    Each route value may be either a scalar registry key or a non-empty ordered
    list of registry keys. Scalars normalize to a one-entry ladder.
    """
    if raw is None or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"STAGE_ROUTING must be valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("STAGE_ROUTING must be a JSON object of {stage: key}")
    routing: dict[str, tuple[str, ...]] = {}
    for stage, route in data.items():
        if isinstance(route, str) and route:
            routing[stage] = (route,)
            continue
        if isinstance(route, list):
            if not route:
                raise ValueError(f"STAGE_ROUTING[{stage!r}] must be a non-empty route")
            if not all(isinstance(key, str) and key for key in route):
                raise ValueError(
                    f"STAGE_ROUTING[{stage!r}] list entries must be non-empty string keys"
                )
            routing[stage] = tuple(route)
            continue
        raise ValueError(
            f"STAGE_ROUTING[{stage!r}] must be a non-empty string key or list of keys"
        )
    return routing


def resolve_profile(
    registry: Mapping[str, ModelProfile],
    routing: StageRouting,
    stage: str,
) -> ModelProfile:
    return resolve_profile_for_tier(registry, routing, stage, 0)


def resolve_profile_for_tier(
    registry: Mapping[str, ModelProfile],
    routing: StageRouting,
    stage: str,
    tier: int,
) -> ModelProfile:
    """Pick the ModelProfile for ``stage``. Fail-closed (KTD5).

    Resolution order: the stage's mapped key, else a registry ``"default"``
    entry, else raise. A stage mapped to a key absent from the registry raises.
    """
    if tier < 0:
        raise ValueError(f"stage {stage!r} tier {tier} is out of range")
    route = routing.get(stage)
    if route is None:
        if "default" in registry:
            if tier != 0:
                raise ValueError(f"stage {stage!r} tier {tier} is out of range")
            return registry["default"]
        raise ValueError(
            f"no model route for stage {stage!r} and no 'default' profile in registry"
        )
    if tier >= len(route):
        raise ValueError(f"stage {stage!r} tier {tier} is out of range")
    key = route[tier]
    if key not in registry:
        raise ValueError(
            f"stage {stage!r} routes to model key {key!r} which is not in the registry"
        )
    return registry[key]


def ladder_length_for(routing: StageRouting, stage: str) -> int:
    route = routing.get(stage)
    if route is None:
        return 1
    return len(route)


def credential_for(profile: ModelProfile, env: Mapping[str, str]) -> str:
    """Read the profile's credential value from ``env``. Fail-closed: raises if
    the named var is unset or empty, so a misconfigured profile never runs
    Goose with no key."""
    value = env.get(profile.credential_env)
    if value is None or not value.strip():
        raise ValueError(
            f"model profile {profile.key!r} needs env var {profile.credential_env}, which is unset"
        )
    return value
