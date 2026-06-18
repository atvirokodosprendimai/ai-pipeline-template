from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import yaml

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class PromptRenderError(Exception):
    pass


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
