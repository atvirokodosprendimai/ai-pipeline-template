from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from wgmesh_pipeline import tracing
from wgmesh_pipeline.config import DEFAULT_GOOSE_MODEL, DEFAULT_GOOSE_PROVIDER, Config
from wgmesh_pipeline.goose.runner import GooseResult
from wgmesh_pipeline.goose.usage import UsageTotals
from wgmesh_pipeline.langchain_agent import prompts
from wgmesh_pipeline.langchain_agent.tools import build_tools, resolve_workspace_path
from wgmesh_pipeline.models import (
    ModelProfile,
    credential_for,
    resolve_profile_for_tier,
)

ClientFactory = Callable[[ModelProfile, Config], Any]
MAX_ITERATIONS = 40
MAX_TOOL_OUTPUT_CHARS = 16_000
WALL_CLOCK_LIMIT_SECONDS = 1800
_LOGGER = logging.getLogger(__name__)


class LangchainAgentRunner:
    def __init__(self, config: Config, *, client_factory: ClientFactory | None = None):
        self.config = config
        self._client_factory = client_factory or _default_client_factory

    def run_recipe(
        self,
        *,
        recipe: str | Path,
        workdir: str | Path,
        params: Mapping[str, str],
        expected_output: str | Path,
        stage: str | None = None,
        tier: int = 0,
        session_id: str | None = None,
    ) -> GooseResult:
        started = time.monotonic()
        raw_log: list[str] = []
        usage = _empty_usage()
        profile: ModelProfile | None = None
        output_path: Path | None = None
        max_iterations = _max_iterations()
        try:
            root = Path(workdir).resolve()
            output_path = resolve_workspace_path(root, expected_output)
            profile = self._resolve_profile(stage, tier)
            try:
                rendered_prompt = prompts.render_recipe_prompt(
                    recipe, params, workdir=root
                )
            except prompts.PromptRenderError as exc:
                return _result(
                    ok=False,
                    output_path=output_path,
                    started=started,
                    raw_log=raw_log,
                    error=str(exc),
                    profile=profile,
                    usage=usage,
                )

            tool_specs, dispatch = build_tools(root)
            client = self._client_factory(profile, self.config)
            llm = client.bind_tools(tool_specs)

            HumanMessage, SystemMessage, ToolMessage = _message_classes()
            messages: list[Any] = [
                SystemMessage(content=_system_prompt()),
                HumanMessage(content=rendered_prompt),
            ]
            raw_log.append(f"system: {_system_prompt()}")
            raw_log.append(f"human: {rendered_prompt}")

            iterations = 0
            completion_text: str | None = None
            while iterations < max_iterations:
                if time.monotonic() - started > WALL_CLOCK_LIMIT_SECONDS:
                    _emit_usage(
                        session_id=session_id,
                        stage=stage,
                        model=profile.model,
                        usage=usage,
                        output=completion_text,
                    )
                    return _result(
                        ok=False,
                        output_path=output_path,
                        started=started,
                        raw_log=raw_log,
                        error=f"langchain agent timed out after {WALL_CLOCK_LIMIT_SECONDS}s",
                        profile=profile,
                        usage=usage,
                    )
                iterations += 1
                ai_message = llm.invoke(messages)
                messages.append(ai_message)
                usage = _add_usage(usage, getattr(ai_message, "usage_metadata", None))
                completion_text = _message_content(ai_message)
                raw_log.append(f"assistant: {completion_text}")

                tool_calls = list(getattr(ai_message, "tool_calls", None) or [])
                # Agent-trace observability (non-goose executor build): the box
                # journal was blind to what the ReAct agent actually does — this
                # surfaces the per-iteration tool sequence so "no tree changes" /
                # tiny-token runs are explainable (e.g. agent runs only run_bash,
                # never read_file/edit_file → it skipped the implementation).
                _LOGGER.info(
                    "agent trace stage=%s iter=%d tools=%s text_len=%d",
                    stage,
                    iterations,
                    [_tool_call_parts(call)[0] for call in tool_calls],
                    len(completion_text or ""),
                )
                if not tool_calls:
                    break

                for call in tool_calls:
                    name, args, call_id = _tool_call_parts(call)
                    try:
                        if name not in dispatch:
                            raise ValueError(f"unknown tool: {name}")
                        result = dispatch[name](**args)
                    except Exception as exc:
                        result = f"ERROR: {exc}"
                    raw_log.append(f"tool {name}: {result}")
                    messages.append(
                        ToolMessage(
                            content=_bounded(str(result)),
                            tool_call_id=call_id,
                            name=name,
                        )
                    )
                if output_path.exists() and output_path.stat().st_size > 0:
                    _emit_usage(
                        session_id=session_id,
                        stage=stage,
                        model=profile.model,
                        usage=usage,
                        output=completion_text,
                    )
                    return _result(
                        ok=True,
                        output_path=output_path,
                        started=started,
                        raw_log=raw_log,
                        error=None,
                        profile=profile,
                        usage=usage,
                    )
            else:
                _emit_usage(
                    session_id=session_id,
                    stage=stage,
                    model=profile.model,
                    usage=usage,
                    output=completion_text,
                )
                return _result(
                    ok=False,
                    output_path=output_path,
                    started=started,
                    raw_log=raw_log,
                    error=f"langchain agent reached max iterations ({max_iterations})",
                    profile=profile,
                    usage=usage,
                )

            _emit_usage(
                session_id=session_id,
                stage=stage,
                model=profile.model,
                usage=usage,
                output=completion_text,
            )
            if output_path.exists():
                return _result(
                    ok=True,
                    output_path=output_path,
                    started=started,
                    raw_log=raw_log,
                    error=None,
                    profile=profile,
                    usage=usage,
                )
            return _result(
                ok=False,
                output_path=output_path,
                started=started,
                raw_log=raw_log,
                error=f"expected output was not written: {output_path}",
                profile=profile,
                usage=usage,
            )
        except Exception as exc:
            return _result(
                ok=False,
                output_path=output_path,
                started=started,
                raw_log=raw_log,
                error=f"langchain agent failed: {exc}",
                profile=profile,
                usage=usage,
            )

    def _resolve_profile(self, stage: str | None, tier: int) -> ModelProfile:
        registry = getattr(self.config, "model_registry", {}) or {}
        routing = getattr(self.config, "stage_routing", {}) or {}
        if stage is not None and registry:
            return resolve_profile_for_tier(registry, routing, stage, tier)
        return ModelProfile(
            key="default",
            provider=getattr(self.config, "goose_provider", DEFAULT_GOOSE_PROVIDER),
            model=getattr(self.config, "goose_model", DEFAULT_GOOSE_MODEL),
            billing="native",
            credential_env="ZAI_API_KEY",
            host=getattr(self.config, "anthropic_host", None),
        )


def _default_client_factory(profile: ModelProfile, config: Config) -> Any:
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=profile.model,
        base_url=profile.host or getattr(config, "anthropic_host", None),
        api_key=credential_for(profile, _credential_env(config)),
        timeout=60,
        max_retries=2,
    )


def _credential_env(config: Config) -> Mapping[str, str]:
    env = dict(os.environ)
    if getattr(config, "zai_api_key", None):
        env.setdefault("ZAI_API_KEY", config.zai_api_key or "")
    return env


def _max_iterations() -> int:
    raw = os.environ.get("LANGCHAIN_MAX_ITERATIONS")
    if raw is None:
        return MAX_ITERATIONS
    try:
        return int(raw)
    except ValueError:
        _LOGGER.warning(
            "invalid LANGCHAIN_MAX_ITERATIONS=%r; using default %s",
            raw,
            MAX_ITERATIONS,
        )
        return MAX_ITERATIONS


def _bounded(text: str) -> str:
    if len(text) <= MAX_TOOL_OUTPUT_CHARS:
        return text
    head_chars = MAX_TOOL_OUTPUT_CHARS // 2
    tail_chars = MAX_TOOL_OUTPUT_CHARS - head_chars
    dropped_chars = len(text) - MAX_TOOL_OUTPUT_CHARS
    marker = f"\n...[truncated {dropped_chars} chars]...\n"
    return f"{text[:head_chars]}{marker}{text[-tail_chars:]}"


def _message_classes() -> tuple[type[Any], type[Any], type[Any]]:
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

    return HumanMessage, SystemMessage, ToolMessage


def _system_prompt() -> str:
    return (
        "You are an autonomous coding agent. Use the provided workspace tools to "
        "inspect and modify files. Keep all work inside the workspace, and write "
        "the requested expected output before finishing."
    )


def _tool_call_parts(call: Any) -> tuple[str, dict[str, Any], str]:
    if isinstance(call, dict):
        return (
            str(call.get("name") or ""),
            dict(call.get("args") or {}),
            str(
                call.get("id")
                or call.get("tool_call_id")
                or call.get("name")
                or "tool-call"
            ),
        )
    return (
        str(getattr(call, "name", "")),
        dict(getattr(call, "args", {}) or {}),
        str(
            getattr(call, "id", None)
            or getattr(call, "tool_call_id", None)
            or getattr(call, "name", None)
            or "tool-call"
        ),
    )


def _message_content(message: Any) -> str:
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else repr(content)


def _add_usage(current: UsageTotals, metadata: Any) -> UsageTotals:
    if not isinstance(metadata, dict):
        return UsageTotals(
            input_tokens=current.input_tokens,
            output_tokens=current.output_tokens,
            total_tokens=current.total_tokens,
            requests=current.requests + 1,
            skipped=current.skipped,
        )
    input_tokens = _usage_int(metadata, "input_tokens")
    output_tokens = _usage_int(metadata, "output_tokens")
    total_tokens = _usage_int(metadata, "total_tokens") or input_tokens + output_tokens
    return UsageTotals(
        input_tokens=current.input_tokens + input_tokens,
        output_tokens=current.output_tokens + output_tokens,
        total_tokens=current.total_tokens + total_tokens,
        requests=current.requests + 1,
        skipped=current.skipped,
    )


def _usage_int(metadata: dict[str, Any], key: str) -> int:
    value = metadata.get(key)
    return value if isinstance(value, int) else 0


def _empty_usage() -> UsageTotals:
    return UsageTotals(
        input_tokens=0, output_tokens=0, total_tokens=0, requests=0, skipped=0
    )


def _emit_usage(
    *,
    session_id: str | None,
    stage: str | None,
    model: str,
    usage: UsageTotals,
    output: str | None = None,
) -> None:
    if usage.total_tokens <= 0:
        return
    tracing.emit_generation(
        session_id=session_id, stage=stage, model=model, usage=usage, output=output
    )


def _result(
    *,
    ok: bool,
    output_path: Path | None,
    started: float,
    raw_log: list[str],
    error: str | None,
    profile: ModelProfile | None,
    usage: UsageTotals,
) -> GooseResult:
    return GooseResult(
        ok=ok,
        output_path=output_path,
        duration_seconds=time.monotonic() - started,
        raw_log="\n".join(raw_log),
        error=error,
        model_key=profile.key if profile is not None else None,
        usage=usage,
    )
