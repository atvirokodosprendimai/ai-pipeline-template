from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

from wgmesh_pipeline.goose.runner import _is_safe_var

ToolDispatch = dict[str, Callable[..., str]]


def _safe_subprocess_env() -> dict[str, str]:
    """Fail-closed env for agent shell tools: copy only allowlisted vars so the
    LLM-driven `run_bash`/`search` never sees the box's secrets (PAT, API keys).
    Mirrors the Goose subprocess allowlist; adds the go-friendly removable module
    cache flag so `go build`/`go test` work inside the workspace checkout."""
    env = {key: value for key, value in os.environ.items() if _is_safe_var(key)}
    env["GOFLAGS"] = (env.get("GOFLAGS", "") + " -modcacherw").strip()
    return env


def resolve_workspace_path(workdir: str | Path, path: str | Path) -> Path:
    root = Path(workdir).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError(f"path escapes workspace: {path}")
    return resolved


def build_tools(workdir: str | Path) -> tuple[list[object], ToolDispatch]:
    root = Path(workdir).resolve()
    safe_env = _safe_subprocess_env()

    def read_file(path: str) -> str:
        resolved = resolve_workspace_path(root, path)
        return resolved.read_text(encoding="utf-8")

    def write_file(path: str, content: str) -> str:
        resolved = resolve_workspace_path(root, path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"wrote {resolved.relative_to(root)}"

    def edit_file(path: str, old: str, new: str) -> str:
        resolved = resolve_workspace_path(root, path)
        content = resolved.read_text(encoding="utf-8")
        if old not in content:
            raise ValueError(f"old text not found in {path}")
        resolved.write_text(content.replace(old, new, 1), encoding="utf-8")
        return f"edited {resolved.relative_to(root)}"

    def run_bash(command: str) -> str:
        completed = subprocess.run(
            command,
            cwd=root,
            shell=True,
            text=True,
            errors="replace",
            capture_output=True,
            check=False,
            timeout=120,
            env=safe_env,
        )
        return (
            f"exit={completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    def search(pattern: str) -> str:
        completed = subprocess.run(
            ["rg", "--", pattern, "."],
            cwd=root,
            text=True,
            errors="replace",
            capture_output=True,
            check=False,
            timeout=120,
            env=safe_env,
        )
        if completed.returncode in {0, 1}:
            return completed.stdout
        return f"exit={completed.returncode}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"

    dispatch: ToolDispatch = {
        "read_file": read_file,
        "write_file": write_file,
        "edit_file": edit_file,
        "run_bash": run_bash,
        "search": search,
    }

    try:
        from langchain_core.tools import StructuredTool
    except ImportError:
        tool_specs = [
            {
                "name": name,
                "description": _TOOL_DESCRIPTIONS[name],
                "parameters": _TOOL_SCHEMAS[name],
            }
            for name in dispatch
        ]
    else:
        tool_specs = [
            StructuredTool.from_function(
                func=read_file,
                name="read_file",
                description=_TOOL_DESCRIPTIONS["read_file"],
            ),
            StructuredTool.from_function(
                func=write_file,
                name="write_file",
                description=_TOOL_DESCRIPTIONS["write_file"],
            ),
            StructuredTool.from_function(
                func=edit_file,
                name="edit_file",
                description=_TOOL_DESCRIPTIONS["edit_file"],
            ),
            StructuredTool.from_function(
                func=run_bash,
                name="run_bash",
                description=_TOOL_DESCRIPTIONS["run_bash"],
            ),
            StructuredTool.from_function(
                func=search,
                name="search",
                description=_TOOL_DESCRIPTIONS["search"],
            ),
        ]
    return tool_specs, dispatch


_TOOL_DESCRIPTIONS = {
    "read_file": "Read a UTF-8 text file inside the workspace.",
    "write_file": "Write UTF-8 text to a file inside the workspace.",
    "edit_file": "Replace the first exact text occurrence in a workspace file.",
    "run_bash": "Run a bash command in the workspace and return exit/stdout/stderr.",
    "search": "Search workspace files with ripgrep and return matching lines.",
}


_TOOL_SCHEMAS = {
    "read_file": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    "write_file": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    "edit_file": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old": {"type": "string"},
            "new": {"type": "string"},
        },
        "required": ["path", "old", "new"],
    },
    "run_bash": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
    "search": {
        "type": "object",
        "properties": {"pattern": {"type": "string"}},
        "required": ["pattern"],
    },
}
