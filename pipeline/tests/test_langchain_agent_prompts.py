from __future__ import annotations

from pathlib import Path

import pytest

from wgmesh_pipeline.langchain_agent.prompts import (
    PromptRenderError,
    render_recipe_prompt,
)

pytestmark = pytest.mark.unit

RECIPES_DIR = Path(__file__).parent.parent / "recipes"


def test_spec_recipe_renders_required_params() -> None:
    rendered = render_recipe_prompt(
        RECIPES_DIR / "wgmesh-triage-spec.yaml",
        {
            "issue_number": "42",
            "issue_title": "Test title",
            "spec_file": "spec.md",
        },
    )

    assert "42" in rendered
    assert "Test title" in rendered
    assert "spec.md" in rendered
    assert "{{" not in rendered
    assert "}}" not in rendered


def test_implementation_recipe_renders_required_params() -> None:
    rendered = render_recipe_prompt(
        RECIPES_DIR / "wgmesh-implementation.yaml",
        {
            "spec_file": "spec.md",
            "diff_file": "diff.patch",
        },
    )

    assert "spec.md" in rendered
    assert "diff.patch" in rendered
    assert "{{" not in rendered
    assert "}}" not in rendered


def test_missing_required_param_names_missing_key(tmp_path: Path) -> None:
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(
        "version: '1'\nprompt: 'Write {{ output_file }}.'\n",
        encoding="utf-8",
    )

    with pytest.raises(PromptRenderError, match="output_file"):
        render_recipe_prompt(recipe, {})


def test_extra_unknown_param_is_ignored(tmp_path: Path) -> None:
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(
        "version: '1'\nprompt: 'Write {{ output_file }}.'\n",
        encoding="utf-8",
    )

    rendered = render_recipe_prompt(
        recipe,
        {"output_file": "out.txt", "unknown": "ignored"},
    )

    assert rendered == "Write out.txt."


def test_recipe_missing_prompt_field_raises_prompt_error(tmp_path: Path) -> None:
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text("version: '1'\n", encoding="utf-8")

    with pytest.raises(PromptRenderError, match="recipe missing top-level prompt"):
        render_recipe_prompt(recipe, {})


def test_recipe_yaml_list_raises_prompt_error(tmp_path: Path) -> None:
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text("- prompt: nope\n", encoding="utf-8")

    with pytest.raises(PromptRenderError):
        render_recipe_prompt(recipe, {})


def test_workdir_resolves_relative_recipe_path(tmp_path: Path) -> None:
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(
        "version: '1'\nprompt: 'Write {{ output_file }}.'\n",
        encoding="utf-8",
    )

    rendered = render_recipe_prompt(
        "recipe.yaml",
        {"output_file": "out.txt"},
        workdir=tmp_path,
    )

    assert rendered == "Write out.txt."
