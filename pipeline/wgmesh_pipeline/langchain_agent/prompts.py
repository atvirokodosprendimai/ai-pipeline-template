from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import yaml

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class PromptRenderError(Exception):
    pass


IMPLEMENT_SYSTEM_PROMPT = (
    "You are an autonomous coding agent. Use the provided workspace tools to "
    "inspect and modify files. For implementation tasks, finishing means the "
    "approved spec has been implemented in the source tree and verified. It "
    "does not mean an output artifact, diff file, or packaging command exists."
)


def load_recipe(recipe_path: str | Path) -> dict:
    try:
        data = yaml.safe_load(Path(recipe_path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise PromptRenderError(f"could not read recipe {recipe_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PromptRenderError("recipe must be a mapping")
    return data


def render_recipe_prompt(
    recipe: str | Path,
    params: Mapping[str, str],
    *,
    workdir: str | Path | None = None,
) -> str:
    recipe_path = Path(recipe)
    if workdir is not None and not recipe_path.is_absolute():
        recipe_path = Path(workdir) / recipe_path

    data = load_recipe(recipe_path)
    prompt_text = data.get("prompt")
    if not isinstance(prompt_text, str):
        raise PromptRenderError("recipe missing top-level prompt")

    declared_required = {
        param["key"]
        for param in data.get("parameters", [])
        if param.get("requirement") == "required"
    }
    placeholders_in_prompt = set(_PLACEHOLDER_RE.findall(prompt_text))
    must_supply = declared_required | placeholders_in_prompt
    missing = must_supply - set(params)
    if missing:
        raise PromptRenderError(
            f"missing required recipe params: {', '.join(sorted(missing))}"
        )

    return _PLACEHOLDER_RE.sub(lambda match: str(params[match.group(1)]), prompt_text)


def build_implement_prompt(spec_file: str | None) -> str:
    if not spec_file:
        raise PromptRenderError("missing required recipe params: spec_file")

    return f"""Implement the approved wgmesh spec at {spec_file}.

You are working in the wgmesh repository:
- Go module: github.com/atvirokodosprendimai/wgmesh
- Go version: 1.25
- Prefer the Go standard library where it is sufficient.
- Preserve existing project style and keep changes scoped to the spec.
- Wrap errors with useful context when returning them.

Required workflow:
1. Read {spec_file} thoroughly.
2. Read the real source files the spec touches. Verify referenced packages, types,
   functions, methods, fields, and signatures exist before using or changing them.
3. IMPLEMENT by EDITING FILES with edit_file or write_file.
   File edits are the deliverable.
4. Verify the implementation with run_bash:
   - go build ./...
   - go test ./...
   - go vet ./...
5. Run gofmt -w on changed Go files.
6. If any verification command fails, inspect the failure, edit the source, and
   repeat verification until the implementation is clean or you are blocked by a
   real repository problem.

Do not write a diff file.
Do not run git staging commands.
Do not run git comparison commands.
Do not run packaging commands.
The pipeline derives the diff from your file edits.

Stop when the implementation is complete and the repository builds, tests, and vets cleanly.
"""
