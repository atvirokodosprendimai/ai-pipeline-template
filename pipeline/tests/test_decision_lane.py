"""Decision-lane orchestrator (U7) — the consent loop, plan + execute."""

from __future__ import annotations

from typing import Any

from wgmesh_pipeline.decision_lane import run_decision_cycle
from wgmesh_pipeline.state.store import StateStore

BOT = "autobox-box"


class FakeForge:
    """Records writes; serves canned asks/comments/votes per post id."""

    def __init__(self, asks, comments=None, votes=None) -> None:
        self._asks = asks
        self._comments = comments or {}
        self._votes = votes or {}
        self.writes: list[tuple[str, Any]] = []

    def list_decision_asks(self):
        return list(self._asks)

    def list_post_comments(self, post_id):
        return list(self._comments.get(post_id, []))

    def post_vote_count(self, post_id):
        return int(self._votes.get(post_id, 0))

    def post_proposal_comment(self, post_id, body):
        self.writes.append(("comment", (post_id, body)))

    def open_final_proposal(self, title, body):
        self.writes.append(("final", (title, body)))
        return {"id": "post_final"}

    def mark_superseded(self, post_id, final_ref):
        self.writes.append(("superseded", (post_id, final_ref)))


def _store(tmp_path):
    return StateStore(tmp_path / "state.db")


def _proposal(post, latest):
    return f"## Recommendation\nfor {post['id']}"


def _run(forge, store, *, live, cofounders=2, max_iters=3):
    return run_decision_cycle(
        forge, store, _proposal,
        bot_author=BOT, cofounder_count=cofounders, max_iterations=max_iters, live=live,
    )


def test_fresh_ask_plans_and_drafts_a_proposal(tmp_path) -> None:
    forge = FakeForge(asks=[{"id": "p1", "title": "Decide pricing"}])
    store = _store(tmp_path)

    result = _run(forge, store, live=True)

    assert result.seen == 1
    assert result.planned[0].kind == "draft"
    assert ("comment", ("p1", "## Recommendation\nfor p1")) in forge.writes
    assert store.get_decision_state("p1")["iterations"] == 1


def test_shadow_plans_but_writes_nothing(tmp_path) -> None:
    forge = FakeForge(asks=[{"id": "p1", "title": "Decide pricing"}])
    store = _store(tmp_path)

    result = _run(forge, store, live=False)

    assert result.planned[0].kind == "draft"
    assert result.executed == 0
    assert forge.writes == []  # zero board writes in shadow
    assert store.get_decision_state("p1") is None  # nothing recorded


def test_new_cofounder_comment_triggers_revise(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_decision_proposal("p1", last_comment_id=None)  # v1 already drafted
    forge = FakeForge(
        asks=[{"id": "p1", "title": "Decide pricing"}],
        comments={"p1": [{"id": "c9", "authorName": "marty", "isTeamMember": True,
                          "createdAt": "2026-06-22T11:00:00Z"}]},
    )

    result = _run(forge, store, live=True)

    assert result.planned[0].kind == "revise"
    assert ("comment", ("p1", "## Recommendation\nfor p1")) in forge.writes
    assert store.get_decision_state("p1")["last_comment_id"] == "c9"


def test_bot_own_comment_does_not_trigger_revise(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_decision_proposal("p1", last_comment_id=None)
    forge = FakeForge(
        asks=[{"id": "p1", "title": "Decide pricing"}],
        comments={"p1": [{"id": "c9", "authorName": BOT, "isTeamMember": True,
                          "createdAt": "2026-06-22T11:00:00Z"}]},
        votes={"p1": 0},
    )

    result = _run(forge, store, live=True)

    assert result.planned[0].kind == "noop"  # no new co-founder feedback, no votes


def test_threshold_met_finalizes_and_supersedes(tmp_path) -> None:
    store = _store(tmp_path)
    store.record_decision_proposal("p1", last_comment_id="c9")  # proposal stands
    forge = FakeForge(
        asks=[{"id": "p1", "title": "Decide pricing"}],
        comments={"p1": [{"id": "c9", "authorName": "marty", "isTeamMember": True,
                          "createdAt": "2026-06-22T11:00:00Z"}]},
        votes={"p1": 1},  # routine threshold = 1
    )

    result = _run(forge, store, live=True)

    assert result.planned[0].kind == "finalize"
    kinds = [w[0] for w in forge.writes]
    assert "final" in kinds and "superseded" in kinds


def test_max_iterations_caps_revision(tmp_path) -> None:
    store = _store(tmp_path)
    for _ in range(3):  # already at the cap (max_iters=3)
        store.record_decision_proposal("p1", last_comment_id="old")
    forge = FakeForge(
        asks=[{"id": "p1", "title": "Decide pricing"}],
        comments={"p1": [{"id": "cNEW", "authorName": "marty", "isTeamMember": True,
                          "createdAt": "2026-06-22T12:00:00Z"}]},
    )

    result = _run(forge, store, live=True, max_iters=3)

    assert result.planned[0].kind == "noop"
    assert result.planned[0].detail == "max iterations reached"


def test_one_bad_post_does_not_kill_the_cycle(tmp_path) -> None:
    class Boom(FakeForge):
        def list_post_comments(self, post_id):
            if post_id == "p1":
                raise RuntimeError("read failed")
            return []

    store = _store(tmp_path)
    store.record_decision_proposal("p1", last_comment_id=None)
    forge = Boom(
        asks=[{"id": "p1", "title": "bad"}, {"id": "p2", "title": "good"}],
        votes={"p2": 0},
    )

    result = _run(forge, store, live=True)

    assert result.seen == 2  # p2 still processed despite p1 raising
