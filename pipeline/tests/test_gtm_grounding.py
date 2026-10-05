from __future__ import annotations

import os
from pathlib import Path

from wgmesh_pipeline.learnings import select_learnings, write_learnings_file

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_gtm_query_finds_vendored_playbook_entry() -> None:
    # a GTM list-building/outreach job grounds on the Core Four playbook entry
    blob = select_learnings("build a warm stargazer outreach lead list", root=REPO_ROOT)
    assert blob
    assert "stargazers are warm" in blob.lower() or "core four" in blob.lower()


def test_positioning_query_finds_obviously_awesome() -> None:
    blob = select_learnings(
        "competitor recon: cloudroof vs headscale alternatives comparison", root=REPO_ROOT
    )
    assert "alternatives" in blob.lower()


def test_unrelated_query_grounds_empty() -> None:
    # fail-open: no GTM match → empty, never an error
    assert select_learnings("xyzzy unrelated frobnicate nonsense", root=REPO_ROOT) == ""


def test_write_learnings_file_for_gtm_job() -> None:
    path = write_learnings_file("warm stargazer outreach list building", root=REPO_ROOT)
    try:
        assert path  # vendored corpus matched → a grounding file exists
        assert "Past learning:" in Path(path).read_text()
    finally:
        if path:
            os.unlink(path)
