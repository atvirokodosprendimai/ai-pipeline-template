"""Relevance selector over the ``docs/solutions/`` learnings corpus.

Pure, deterministic read-back half of observe -> score -> *improve*: rank the
committed learnings by token overlap against a query (an issue title/body, or a
spec), and return the top-N concatenated within a char budget so they can be
injected into the spec/implement agent recipes as advisory "known pitfalls".

No network, no embeddings, no LLM. Fail-open per file: a malformed entry is
skipped, never raised, so injecting learnings can never break a build run.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger("wgmesh_pipeline.learnings")

_SOLUTIONS_REL = ("docs", "solutions")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MIN_TOKEN_LEN = 3
_TAG_WEIGHT = 2

# Machine-countable, body-unique block header so callers/tests can delimit
# entries even though entry bodies themselves contain markdown headings.
_BLOCK_HEADER = "## Past learning:"
_PARTIAL_MARKER = (
    "\n...[truncated — PARTIAL learning, char budget reached; "
    "this is the head of the most relevant entry]...\n"
)


@dataclass(frozen=True)
class _Entry:
    title: str
    category: str
    tags: tuple[str, ...]
    date: str
    body: str


def _tokenize(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= _MIN_TOKEN_LEN}


def _date_key(date: str) -> tuple[int, int, int]:
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", date or "")
    if not match:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _parse_file(path: Path) -> _Entry | None:
    """Parse one corpus file; return None (skip) on any malformed input."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.startswith("---"):
        return None
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None

    raw_tags = meta.get("tags", [])
    if isinstance(raw_tags, str):
        tags = tuple(t.strip() for t in raw_tags.replace(",", " ").split() if t.strip())
    elif isinstance(raw_tags, (list, tuple)):
        tags = tuple(str(t) for t in raw_tags)
    else:
        tags = ()

    return _Entry(
        title=str(meta.get("title", path.stem)),
        category=str(meta.get("category", "")),
        tags=tags,
        date=str(meta.get("date", "")),
        body=parts[2].strip(),
    )


def _score(entry: _Entry, query_tokens: set[str]) -> int:
    tag_tokens: set[str] = set()
    for tag in entry.tags:
        tag_tokens |= _tokenize(tag)
    title_tokens = _tokenize(entry.title) | _tokenize(entry.category)
    return _TAG_WEIGHT * len(query_tokens & tag_tokens) + len(query_tokens & title_tokens)


def _compact_body(body: str) -> str:
    """Trim an entry body to its substance: drop a leading duplicate H1 and any
    trailing ``## Related`` link section."""
    body = body.strip()
    body = re.sub(r"^#\s+.*\n+", "", body, count=1)
    related = re.search(r"(?mi)^##\s+Related\b", body)
    if related:
        body = body[: related.start()].rstrip()
    return body


def _block(entry: _Entry) -> str:
    return f"{_BLOCK_HEADER} {entry.title}\n\n{_compact_body(entry.body)}\n"


def default_corpus_root() -> Path:
    """Repo root holding ``docs/solutions/`` — this pipeline's own checkout, not
    the target repo the agent edits. Derived from this module's location."""
    return Path(__file__).resolve().parents[2]


def write_learnings_file(
    query: str,
    *,
    root: str | Path | None = None,
    prefix: str = "learnings-",
    max_items: int = 3,
    max_chars: int = 4000,
) -> str:
    """Select learnings for ``query`` and write them to a temp file.

    Returns the temp file path, or "" when there are no relevant learnings — so
    callers ALWAYS pass the (required) recipe param, empty on no-match. Fail-open:
    any selector/IO error logs and returns "" rather than raising. The caller owns
    cleanup (unlink in a ``finally``).
    """
    corpus_root = Path(root) if root is not None else default_corpus_root()
    try:
        blob = select_learnings(
            query, root=corpus_root, max_items=max_items, max_chars=max_chars
        )
    except Exception:  # noqa: BLE001 — fail-open; learnings must never break a run
        log.warning("learnings selection failed; proceeding without", exc_info=True)
        return ""
    if not blob.strip():
        return ""
    try:
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(blob)
    except OSError:
        log.warning("learnings temp-file write failed; proceeding without", exc_info=True)
        return ""
    return path


def select_learnings(
    query: str,
    *,
    root: str | Path,
    max_items: int = 3,
    max_chars: int = 4000,
) -> str:
    """Return the learnings most relevant to ``query``, concatenated.

    Globs ``<root>/docs/solutions/**/*.md`` recursively (all corpus files live in
    category subdirs), ranks by token overlap of each entry's tags/category/title
    against the query (tags weighted; recency breaks ties), and concatenates the
    top entries up to ``max_items`` / ``max_chars``. Returns "" when the corpus is
    missing/empty, the query is empty, or nothing scores above zero.
    """
    base = Path(root).joinpath(*_SOLUTIONS_REL)
    if not base.is_dir():
        return ""
    query_tokens = _tokenize(query)
    if not query_tokens:
        return ""

    scored: list[tuple[int, tuple[int, int, int], _Entry]] = []
    for path in base.rglob("*.md"):
        entry = _parse_file(path)
        if entry is None:
            continue
        score = _score(entry, query_tokens)
        if score <= 0:
            continue
        scored.append((score, _date_key(entry.date), entry))
    if not scored:
        return ""

    # score desc, then date desc (newer wins a tie)
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    result = ""
    for _, _, entry in scored[:max_items]:
        block = _block(entry)
        candidate = block if not result else f"{result}\n{block}"
        if result:
            if len(candidate) > max_chars:
                break
        elif len(block) > max_chars:
            # single oversized highest-ranked entry: cut at a line boundary
            head = block[:max_chars].rsplit("\n", 1)[0] or block[:max_chars]
            return head + _PARTIAL_MARKER
        result = candidate
    return result
