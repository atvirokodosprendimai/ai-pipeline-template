"""Forge adapter factory.

Mirrors open_state_store: the kind is EXPLICIT and unknown values fail
closed — no silent fallback to GitHub (the mailservice lesson applied to
host selection).
"""

from __future__ import annotations

from typing import Any

from wgmesh_pipeline.forge.protocol import Forge


def make_forge(config: Any) -> Forge:
    kind = getattr(config, "forge_kind", "github")
    if kind == "github":
        from wgmesh_pipeline.github.client import GitHubClient

        return GitHubClient(config)
    if kind == "gitea":
        from wgmesh_pipeline.forge.gitea import GiteaForge

        return GiteaForge(config)
    if kind == "quackback":
        from wgmesh_pipeline.forge.quackback import QuackbackForge

        return QuackbackForge(config)
    raise ValueError(
        f"unknown forge_kind: {kind!r} (expected 'github', 'gitea', or 'quackback')"
    )
