"""GitHub forge adapter.

The concrete implementation lives in wgmesh_pipeline.github.client (it
predates the forge layer and carries the write gate + sanitise machinery).
This module is the adapter's forge-layer home; callers should reach GitHub
only through make_forge()/Forge.
"""

from __future__ import annotations

from wgmesh_pipeline.github.client import GitHubClient as GitHubForge

__all__ = ["GitHubForge"]
