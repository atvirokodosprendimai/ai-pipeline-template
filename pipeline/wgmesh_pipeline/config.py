from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from wgmesh_pipeline.models import (
    ModelProfile,
    parse_registry,
    parse_stage_routing,
)

log = logging.getLogger(__name__)

# GitOps box config: a committed, non-secret JSON file read as a base layer
# UNDER the environment (env vars override). Lets the box be reconfigured by
# commit + redeploy instead of SSH-editing the env file. PUBLIC repo, so only
# this allowlist of operational toggles is honored — any other key (especially
# secret-shaped: PAT/TOKEN/KEY/PASSWORD/URL) is ignored. Fail-closed against a
# committed secret (allowlist, not denylist — agent-env lesson).
BOX_CONFIG_PATH = Path(__file__).resolve().parents[2] / "company" / "box-config.json"
BOX_CONFIG_ALLOWLIST = frozenset(
    {
        "CONTROL_LOOP_ENABLED",
        "CONTROL_LOOP_MODE",
        "SELFHEAL_INTERVAL_SECONDS",
        "SUPERVISOR_INTERVAL_SECONDS",
        "OBSERVATION_INTERVAL_SECONDS",
        "STRATEGY_AUDIT_INTERVAL_SECONDS",
        "SUPERVISOR_LIVE",
        "SELFHEAL_LIVE",
        "OBSERVATION_LIVE",
        "STRATEGY_AUDIT_LIVE",
        "MERGE_LANE_HEAL_LIVE",
        "MERGE_LANE_HEAL_INTERVAL_SECONDS",
        "DECISION_LANE_LIVE",
        "DECISION_LANE_INTERVAL_SECONDS",
        "DECISION_COFOUNDER_COUNT",
        "DECISION_MAX_ITERATIONS",
        "DECISION_BOT_AUTHOR",
        "DEDUP_SEMANTIC_ENABLED",
        "DEDUP_SIMILARITY_THRESHOLD",
        "EMBEDDINGS_MODEL",
        "EMBEDDINGS_BASE_URL",
        "META_REPO",
        "POLL_INTERVAL_SECONDS",
        "MAX_FILES",
        "EXECUTOR",
        "LLM_REQUEST_TIMEOUT_SECONDS",
        "FORGE_KIND",
        # Quackback Build Suggestions board id — non-secret, lets the cutover
        # set it via box-config or set-box-env (the URL/token stay secrets).
        "QUACKBACK_BOARD_ID",
    }
)


def _read_box_config(path: Path = BOX_CONFIG_PATH) -> dict[str, str]:
    """Allowlisted non-secret toggles from the committed box config, or {}.

    A malformed or absent file is non-fatal (logged) — the box falls back to
    env + defaults, never crashes on a config-file typo."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("box-config unreadable (%s): falling back to env/defaults", exc)
        return {}
    if not isinstance(raw, dict):
        log.warning("box-config is not a JSON object: ignoring")
        return {}
    return {
        k: str(v) for k, v in raw.items() if k in BOX_CONFIG_ALLOWLIST and v is not None
    }


VALID_MODES = frozenset({"shadow", "spec-only", "live"})
VALID_DB_MODES = frozenset({"local", "turso"})
DEFAULT_ANTHROPIC_HOST = "https://api.z.ai/api/anthropic"
DEFAULT_TARGET_REPO = "atvirokodosprendimai/wgmesh"
DEFAULT_POLL_INTERVAL_SECONDS = 300
DEFAULT_MAX_FILES = 20
DEFAULT_REPO_PATH = "/opt/wgmesh-checkout"
DEFAULT_RECIPES_DIR = str(Path(__file__).resolve().parents[1] / "recipes")
DEFAULT_GOOSE_PROVIDER = "anthropic"
DEFAULT_GOOSE_MODEL = "GLM-5.2"
DEFAULT_MAX_ESCALATION_ATTEMPTS = 2

# Control-loop scheduler (cutover Phase B/C, shadow-first). Per-module cadences
# mirror the Actions cron rhythms: self-heal every 30m, supervisor-rank every
# 4h, observation every 8h, strategy-audit daily.
VALID_CONTROL_LOOP_MODES = frozenset({"shadow", "live"})
DEFAULT_CONTROL_LOOP_MODE = "shadow"
DEFAULT_SELFHEAL_INTERVAL_SECONDS = 1800
DEFAULT_SUPERVISOR_INTERVAL_SECONDS = 14400
DEFAULT_OBSERVATION_INTERVAL_SECONDS = 28800
DEFAULT_STRATEGY_AUDIT_INTERVAL_SECONDS = 86400
# Merge-lane-heal: 6h, matching the retired conflict-heal.yml cron (01/07/13/19).
DEFAULT_MERGE_LANE_HEAL_INTERVAL_SECONDS = 21600
DEFAULT_DECISION_LANE_INTERVAL_SECONDS = 3600  # founder decisions, hourly
# LLM client request timeout. The provider (GLM-5.2 on z.ai) is known to run long
# on coding-agent calls; 60s cancelled mid-request → "Request timed out". 600s
# matches Anthropic's long-request window + the replay harness.
DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS = 600
# Semantic dedup (z.ai embeddings). OFF until the endpoint/model/dim is VERIFIED
# against the live z.ai account; until then the forge dedup keeps exact-title.
DEFAULT_EMBEDDINGS_MODEL = "embedding-3"
DEFAULT_EMBEDDINGS_BASE_URL = "https://api.z.ai/api/paas/v4"
DEFAULT_DEDUP_SIMILARITY_THRESHOLD = 0.85
# The meta repo (the pipeline's own repo) — merge-lane-heal heals BOTH repos.
DEFAULT_META_REPO = "atvirokodosprendimai/ai-pipeline-template"


@dataclass(frozen=True)
class Config:
    target_repo: str
    mode: str = "shadow"
    wgmesh_bot_pat: str | None = None
    zai_api_key: str | None = None
    anthropic_host: str = DEFAULT_ANTHROPIC_HOST
    langsmith_api_key: str | None = None
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS
    max_files: int = DEFAULT_MAX_FILES
    repo_path: str = DEFAULT_REPO_PATH
    recipes_dir: str = DEFAULT_RECIPES_DIR
    goose_provider: str = DEFAULT_GOOSE_PROVIDER
    goose_model: str = DEFAULT_GOOSE_MODEL
    forge_kind: str = "github"
    gitea_url: str | None = None
    quackback_url: str | None = None
    quackback_token: str | None = None
    quackback_board_id: str | None = None
    database_mode: str = "local"
    database_path: str = "pipeline/state.db"
    turso_url: str | None = None
    turso_auth_token: str | None = None
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    # Multi-model routing (price/perf #2). Empty by default → callers synthesize
    # a zero-config default profile from the goose_* fields above (R7).
    model_registry: Mapping[str, ModelProfile] = field(default_factory=dict)
    stage_routing: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    max_escalation_attempts: int = DEFAULT_MAX_ESCALATION_ATTEMPTS
    # Control-loop scheduler (shadow-first; only "shadow" is honored in this
    # unit — "live" is forced back to shadow with a loud warning since the
    # executor that performs forge writes + state persistence is a follow-up).
    control_loop_enabled: bool = False
    control_loop_mode: str = DEFAULT_CONTROL_LOOP_MODE
    selfheal_interval_seconds: int = DEFAULT_SELFHEAL_INTERVAL_SECONDS
    supervisor_interval_seconds: int = DEFAULT_SUPERVISOR_INTERVAL_SECONDS
    observation_interval_seconds: int = DEFAULT_OBSERVATION_INTERVAL_SECONDS
    strategy_audit_interval_seconds: int = DEFAULT_STRATEGY_AUDIT_INTERVAL_SECONDS
    supervisor_live: bool = False
    selfheal_live: bool = False
    observation_live: bool = False
    strategy_audit_live: bool = False
    merge_lane_heal_interval_seconds: int = DEFAULT_MERGE_LANE_HEAL_INTERVAL_SECONDS
    merge_lane_heal_live: bool = False
    # Decision lane (capability-ladder Phase 1). Shadow until flipped live.
    decision_lane_live: bool = False
    decision_lane_interval_seconds: int = DEFAULT_DECISION_LANE_INTERVAL_SECONDS
    decision_cofounder_count: int = 2
    decision_max_iterations: int = 5
    # The bot key's authorName on the board — its own comments are excluded from
    # the "new co-founder comment" iteration trigger (KTD5).
    decision_bot_author: str = "autobox-box"
    # Semantic dedup (z.ai embeddings); see DEFAULT_* notes above.
    dedup_semantic_enabled: bool = False
    dedup_similarity_threshold: float = DEFAULT_DEDUP_SIMILARITY_THRESHOLD
    embeddings_model: str = DEFAULT_EMBEDDINGS_MODEL
    embeddings_base_url: str = DEFAULT_EMBEDDINGS_BASE_URL
    meta_repo: str = DEFAULT_META_REPO
    # Executor backend: 'goose' (default) or 'langchain' (U2).
    # Selected via EXECUTOR env var; factory in executor.py fails closed on unknown values.
    llm_request_timeout_seconds: int = DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS
    executor: str = "goose"
    # Per-surface executor overrides (U1): the observation-assess and
    # decision-proposal surfaces select their backend independently, each
    # defaulting to `executor` (then "goose"). Lets each surface flip to
    # langchain on its own via OBSERVATION_EXECUTOR / DECISION_EXECUTOR.
    observation_executor: str = "goose"
    decision_executor: str = "goose"
    # Graph backend: 'legacy' (default) or 'langgraph' (U4).
    # Selected via GRAPH_IMPL env var; build_graph dispatches on this value.
    graph_impl: str = "legacy"

    @property
    def owner(self) -> str:
        return self.target_repo.split("/", 1)[0]

    @property
    def repo(self) -> str:
        return self.target_repo.split("/", 1)[1]


def load_config(env: Mapping[str, str] | None = None) -> Config:
    # Runtime path (env is None): layer the committed box-config UNDER the
    # process environment so a real env var always wins. Tests pass an explicit
    # `env` and stay hermetic — the committed file never bleeds into them.
    if env is None:
        source: Mapping[str, str] = {**_read_box_config(), **os.environ}
    else:
        source = env

    target_repo = _required(source, "TARGET_REPO")
    mode = _get_nonempty(source, "PIPELINE_MODE") or "shadow"
    if mode not in VALID_MODES:
        valid = ", ".join(sorted(VALID_MODES))
        raise ValueError(f"PIPELINE_MODE must be one of: {valid}; got {mode!r}")

    if "/" not in target_repo or target_repo.count("/") != 1:
        raise ValueError("TARGET_REPO must be in owner/repo form")

    pat = _get_nonempty(source, "WGMESH_BOT_PAT")
    if mode == "live" and not pat:
        raise ValueError("WGMESH_BOT_PAT is required when PIPELINE_MODE=live")

    # Explicit database selection — no silent fallback (mailservice lesson: a
    # misconfigured deploy must fail, not silently write to a local file).
    db_mode = _required(source, "DATABASE_MODE").lower()
    if db_mode not in VALID_DB_MODES:
        valid = ", ".join(sorted(VALID_DB_MODES))
        raise ValueError(f"DATABASE_MODE must be one of: {valid}; got {db_mode!r}")
    turso_url = _get_nonempty(source, "TURSO_DATABASE_URL")
    turso_token = _get_nonempty(source, "TURSO_AUTH_TOKEN")
    if db_mode == "turso" and not turso_url:
        raise ValueError("DATABASE_MODE=turso requires TURSO_DATABASE_URL")

    forge_kind = _get_nonempty(source, "FORGE_KIND") or "github"
    quackback_url = _get_nonempty(source, "QUACKBACK_URL")
    quackback_token = _get_nonempty(source, "QUACKBACK_TOKEN")
    quackback_board_id = _get_nonempty(source, "QUACKBACK_BOARD_ID")
    if forge_kind == "quackback" and not (
        quackback_url and quackback_token and quackback_board_id
    ):
        raise ValueError(
            "forge_kind=quackback requires QUACKBACK_URL, QUACKBACK_TOKEN, "
            "and QUACKBACK_BOARD_ID"
        )

    control_loop_mode = (
        _get_nonempty(source, "CONTROL_LOOP_MODE") or DEFAULT_CONTROL_LOOP_MODE
    ).lower()
    if control_loop_mode not in VALID_CONTROL_LOOP_MODES:
        valid = ", ".join(sorted(VALID_CONTROL_LOOP_MODES))
        raise ValueError(
            f"CONTROL_LOOP_MODE must be one of: {valid}; got {control_loop_mode!r}"
        )

    goose_provider = _get_nonempty(source, "GOOSE_PROVIDER") or DEFAULT_GOOSE_PROVIDER
    goose_model = _get_nonempty(source, "GOOSE_MODEL") or DEFAULT_GOOSE_MODEL
    anthropic_host = _get_nonempty(source, "ANTHROPIC_HOST") or DEFAULT_ANTHROPIC_HOST
    model_registry, stage_routing = _build_routing(
        source,
        goose_provider=goose_provider,
        goose_model=goose_model,
        anthropic_host=anthropic_host,
    )

    cfg = Config(
        target_repo=target_repo,
        mode=mode,
        wgmesh_bot_pat=pat,
        zai_api_key=_get_nonempty(source, "ZAI_API_KEY"),
        anthropic_host=anthropic_host,
        langsmith_api_key=_get_nonempty(source, "LANGSMITH_API_KEY"),
        forge_kind=forge_kind,
        gitea_url=_get_nonempty(source, "GITEA_URL"),
        quackback_url=quackback_url,
        quackback_token=quackback_token,
        quackback_board_id=quackback_board_id,
        poll_interval_seconds=_get_int(
            source, "POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS
        ),
        max_files=_get_int(source, "MAX_FILES", DEFAULT_MAX_FILES),
        repo_path=_get_nonempty(source, "WGMESH_CHECKOUT_PATH") or DEFAULT_REPO_PATH,
        recipes_dir=_get_nonempty(source, "RECIPES_DIR") or DEFAULT_RECIPES_DIR,
        goose_provider=goose_provider,
        goose_model=goose_model,
        database_mode=db_mode,
        database_path=_get_nonempty(source, "PIPELINE_DB_PATH") or "pipeline/state.db",
        turso_url=turso_url,
        turso_auth_token=turso_token,
        langfuse_host=_get_nonempty(source, "LANGFUSE_HOST"),
        langfuse_public_key=_get_nonempty(source, "LANGFUSE_PUBLIC_KEY"),
        langfuse_secret_key=_get_nonempty(source, "LANGFUSE_SECRET_KEY"),
        model_registry=model_registry,
        stage_routing=stage_routing,
        max_escalation_attempts=_get_int(
            source,
            "MAX_ESCALATION_ATTEMPTS",
            DEFAULT_MAX_ESCALATION_ATTEMPTS,
        ),
        control_loop_enabled=_truthy(_get_nonempty(source, "CONTROL_LOOP_ENABLED")),
        control_loop_mode=control_loop_mode,
        selfheal_interval_seconds=_get_int(
            source, "SELFHEAL_INTERVAL_SECONDS", DEFAULT_SELFHEAL_INTERVAL_SECONDS
        ),
        supervisor_interval_seconds=_get_int(
            source, "SUPERVISOR_INTERVAL_SECONDS", DEFAULT_SUPERVISOR_INTERVAL_SECONDS
        ),
        observation_interval_seconds=_get_int(
            source, "OBSERVATION_INTERVAL_SECONDS", DEFAULT_OBSERVATION_INTERVAL_SECONDS
        ),
        strategy_audit_interval_seconds=_get_int(
            source,
            "STRATEGY_AUDIT_INTERVAL_SECONDS",
            DEFAULT_STRATEGY_AUDIT_INTERVAL_SECONDS,
        ),
        supervisor_live=_get_bool(source, "SUPERVISOR_LIVE", False),
        selfheal_live=_get_bool(source, "SELFHEAL_LIVE", False),
        observation_live=_get_bool(source, "OBSERVATION_LIVE", False),
        strategy_audit_live=_get_bool(source, "STRATEGY_AUDIT_LIVE", False),
        merge_lane_heal_interval_seconds=_get_int(
            source,
            "MERGE_LANE_HEAL_INTERVAL_SECONDS",
            DEFAULT_MERGE_LANE_HEAL_INTERVAL_SECONDS,
        ),
        merge_lane_heal_live=_get_bool(source, "MERGE_LANE_HEAL_LIVE", False),
        decision_lane_live=_get_bool(source, "DECISION_LANE_LIVE", False),
        decision_lane_interval_seconds=_get_int(
            source,
            "DECISION_LANE_INTERVAL_SECONDS",
            DEFAULT_DECISION_LANE_INTERVAL_SECONDS,
        ),
        decision_cofounder_count=_get_int(source, "DECISION_COFOUNDER_COUNT", 2),
        decision_max_iterations=_get_int(source, "DECISION_MAX_ITERATIONS", 5),
        decision_bot_author=_get_nonempty(source, "DECISION_BOT_AUTHOR")
        or "autobox-box",
        dedup_semantic_enabled=_get_bool(source, "DEDUP_SEMANTIC_ENABLED", False),
        dedup_similarity_threshold=_get_float(
            source, "DEDUP_SIMILARITY_THRESHOLD", DEFAULT_DEDUP_SIMILARITY_THRESHOLD
        ),
        embeddings_model=_get_nonempty(source, "EMBEDDINGS_MODEL")
        or DEFAULT_EMBEDDINGS_MODEL,
        embeddings_base_url=_get_nonempty(source, "EMBEDDINGS_BASE_URL")
        or DEFAULT_EMBEDDINGS_BASE_URL,
        meta_repo=_get_nonempty(source, "META_REPO") or DEFAULT_META_REPO,
        executor=(_get_nonempty(source, "EXECUTOR") or "goose").strip().lower(),
        observation_executor=(
            _get_nonempty(source, "OBSERVATION_EXECUTOR")
            or _get_nonempty(source, "EXECUTOR")
            or "goose"
        )
        .strip()
        .lower(),
        decision_executor=(
            _get_nonempty(source, "DECISION_EXECUTOR")
            or _get_nonempty(source, "EXECUTOR")
            or "goose"
        )
        .strip()
        .lower(),
        llm_request_timeout_seconds=_get_int(
            source, "LLM_REQUEST_TIMEOUT_SECONDS", DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS
        ),
        graph_impl=(_get_nonempty(source, "GRAPH_IMPL") or "legacy").strip().lower(),
    )
    _log_control_loop_module_modes(cfg)
    return cfg


# Goose provider id the zero-config fallback profile uses ANTHROPIC_API_KEY for.
_DEFAULT_CREDENTIAL_ENV = "ZAI_API_KEY"


def _build_routing(
    source: Mapping[str, str],
    *,
    goose_provider: str,
    goose_model: str,
    anthropic_host: str,
) -> tuple[Mapping[str, ModelProfile], Mapping[str, tuple[str, ...]]]:
    """Registry + stage map from env, with a zero-config fallback (R7).

    When MODEL_REGISTRY is unset, synthesize a single ``default`` profile from
    the goose_* fields so the pipeline behaves exactly as it did before routing
    existed: one model, every stage. When set, parse both and trust the
    fail-closed validation in models.py (an unset STAGE_ROUTING is valid as long
    as the registry carries a ``default`` profile)."""
    registry = parse_registry(_get_nonempty(source, "MODEL_REGISTRY"))
    routing = parse_stage_routing(_get_nonempty(source, "STAGE_ROUTING"))
    if not registry:
        registry = {
            "default": ModelProfile(
                key="default",
                provider=goose_provider,
                model=goose_model,
                billing="native",
                credential_env=_DEFAULT_CREDENTIAL_ENV,
                host=anthropic_host,
            )
        }
    return registry, routing


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def _get_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _get_nonempty(env, name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise ValueError(f"{name} must be 'true' or 'false'; got {raw!r}")


def _log_control_loop_module_modes(cfg: Config) -> None:
    for module_name, is_live in (
        ("supervisor", cfg.supervisor_live),
        ("selfheal", cfg.selfheal_live),
        ("observation", cfg.observation_live),
        ("strategy_audit", cfg.strategy_audit_live),
        ("merge_lane", cfg.merge_lane_heal_live),
    ):
        log.info(
            "control_loop: module=%s startup_mode=%s",
            module_name,
            "live" if is_live else "shadow",
        )


def _required(env: Mapping[str, str], name: str) -> str:
    value = _get_nonempty(env, name)
    if value is None:
        raise ValueError(f"{name} is required")
    return value


def _get_nonempty(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _get_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _get_nonempty(env, name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _get_nonempty(env, name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value
