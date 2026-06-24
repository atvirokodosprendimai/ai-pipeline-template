from __future__ import annotations

import os
from pathlib import Path

from wgmesh_pipeline import learnings as learnings_mod
from wgmesh_pipeline.learnings import (
    _BLOCK_HEADER,
    select_learnings,
    write_learnings_file,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write(root: Path, rel: str, *, title: str, tags: list[str], date: str, body: str) -> None:
    """Build a docs/solutions corpus file under ``root`` with YAML frontmatter."""
    path = root / "docs" / "solutions" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = (
        "---\n"
        f'title: "{title}"\n'
        f"category: {path.parent.name}\n"
        f"date: {date}\n"
        f"tags: [{', '.join(tags)}]\n"
        "---\n\n"
        f"{body}\n"
    )
    path.write_text(fm, encoding="utf-8")


# --- scenarios against the real, committed corpus -------------------------


def test_query_overlapping_tags_ranks_matching_learning_first() -> None:
    blob = select_learnings(
        "goose weak model prints spec to stdout instead of writing the file",
        root=REPO_ROOT,
    )
    assert blob  # non-empty
    assert _BLOCK_HEADER in blob
    # the goose-weak-model learning must be the first block
    first_header = blob.index(_BLOCK_HEADER)
    head = blob[first_header : first_header + 200].lower()
    assert "goose" in head and "spec" in head


def test_query_matching_nothing_returns_empty() -> None:
    assert select_learnings("xyzzy quux frobnicate nonsense", root=REPO_ROOT) == ""


def test_empty_query_returns_empty() -> None:
    assert select_learnings("", root=REPO_ROOT) == ""


# --- scenarios against controlled tmp corpora -----------------------------


def test_max_items_caps_returned_blocks(tmp_path: Path) -> None:
    for i in range(5):
        _write(
            tmp_path,
            f"logic-errors/entry-{i}.md",
            title=f"Widget pipeline learning {i}",
            tags=["widget", "pipeline", "shared"],
            date=f"2026-06-0{i + 1}",
            body="## Problem\nThing broke.\n\n## Fix\nFixed it.",
        )
    blob = select_learnings("widget pipeline shared", root=tmp_path, max_items=2)
    assert blob.count(_BLOCK_HEADER) == 2


def test_max_chars_truncates_at_boundary_with_marker(tmp_path: Path) -> None:
    long_body = "\n".join(f"line {n} about widgets" for n in range(200))
    _write(
        tmp_path,
        "logic-errors/huge.md",
        title="Widget overflow learning",
        tags=["widget"],
        date="2026-06-01",
        body=f"## Problem\n{long_body}",
    )
    blob = select_learnings("widget", root=tmp_path, max_chars=400)
    assert blob  # still returns the head of the highest-ranked entry
    assert "partial" in blob.lower()
    # never cut mid-line: the body portion ends on a line boundary
    assert "about widgetsline" not in blob
    # marker is reserved within budget — total stays within max_chars
    assert len(blob) <= 400


def test_max_chars_bound_holds_with_no_newline_in_head(tmp_path: Path) -> None:
    # a long single-line body: the head slice contains no newline to cut on,
    # exercising the `or block[:budget]` fallback — total must still be bounded
    _write(
        tmp_path,
        "logic-errors/oneline.md",
        title="Widget oneline learning",
        tags=["widget"],
        date="2026-06-01",
        body="x" * 5000,
    )
    blob = select_learnings("widget", root=tmp_path, max_chars=1000)
    assert blob
    assert len(blob) <= 1000


def test_malformed_file_skipped_others_ranked(tmp_path: Path) -> None:
    # garbage file with no frontmatter
    bad = tmp_path / "docs" / "solutions" / "logic-errors" / "bad.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("not frontmatter at all\njust prose\n", encoding="utf-8")
    _write(
        tmp_path,
        "logic-errors/good.md",
        title="Widget good learning",
        tags=["widget"],
        date="2026-06-01",
        body="## Problem\nok",
    )
    blob = select_learnings("widget", root=tmp_path)
    assert "Widget good learning" in blob


def test_empty_solutions_dir_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "docs" / "solutions").mkdir(parents=True)
    assert select_learnings("anything", root=tmp_path) == ""


def test_missing_solutions_dir_returns_empty(tmp_path: Path) -> None:
    assert select_learnings("anything", root=tmp_path) == ""


def test_recency_tiebreak_newer_first(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "logic-errors/old.md",
        title="Older equal entry",
        tags=["widget", "shared"],
        date="2026-01-01",
        body="## Problem\nold",
    )
    _write(
        tmp_path,
        "logic-errors/new.md",
        title="Newer equal entry",
        tags=["widget", "shared"],
        date="2026-06-01",
        body="## Problem\nnew",
    )
    blob = select_learnings("widget shared", root=tmp_path)
    assert blob.index("Newer equal entry") < blob.index("Older equal entry")


def test_recursive_glob_finds_subdir_only_files(tmp_path: Path) -> None:
    # file lives ONLY in a nested category subdir, never at top level
    _write(
        tmp_path,
        "integration-issues/nested.md",
        title="Nested subdir learning",
        tags=["widget", "nested"],
        date="2026-06-01",
        body="## Problem\nfound via recursive glob",
    )
    blob = select_learnings("widget nested", root=tmp_path)
    assert "Nested subdir learning" in blob


def test_write_learnings_file_returns_path_with_content(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "logic-errors/good.md",
        title="Widget good learning",
        tags=["widget"],
        date="2026-06-01",
        body="## Problem\nok",
    )
    path = write_learnings_file("widget", root=tmp_path)
    try:
        assert path
        content = Path(path).read_text(encoding="utf-8")
        assert "Widget good learning" in content
    finally:
        if path:
            os.unlink(path)


def test_write_learnings_file_empty_on_no_match(tmp_path: Path) -> None:
    (tmp_path / "docs" / "solutions").mkdir(parents=True)
    assert write_learnings_file("anything", root=tmp_path) == ""


def test_write_learnings_file_no_orphan_on_write_failure(monkeypatch, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "logic-errors/good.md",
        title="Widget good learning",
        tags=["widget"],
        date="2026-06-01",
        body="## Problem\nok",
    )
    created: list[str] = []
    real_mkstemp = learnings_mod.tempfile.mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        created.append(path)
        return fd, path

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(learnings_mod.tempfile, "mkstemp", tracking_mkstemp)
    monkeypatch.setattr(learnings_mod.os, "fdopen", boom)

    assert write_learnings_file("widget", root=tmp_path) == ""
    assert created  # mkstemp ran and created a file
    assert not Path(created[0]).exists()  # orphan cleaned up despite write failure


def test_write_learnings_file_failopen_on_selector_error(monkeypatch, tmp_path: Path) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("selector exploded")

    monkeypatch.setattr(learnings_mod, "select_learnings", boom)
    assert write_learnings_file("widget", root=tmp_path) == ""


def test_default_corpus_root_holds_solutions() -> None:
    from wgmesh_pipeline.learnings import default_corpus_root

    assert (default_corpus_root() / "docs" / "solutions").is_dir()


def test_default_budget_constants() -> None:
    # conservative defaults: top-3 / ~4KB
    import inspect

    sig = inspect.signature(select_learnings)
    assert sig.parameters["max_items"].default == 3
    assert sig.parameters["max_chars"].default == 4000
