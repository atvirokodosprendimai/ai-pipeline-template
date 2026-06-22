from __future__ import annotations

import asyncio

import pytest

from wgmesh_pipeline import main
from wgmesh_pipeline.config import Config


class Store:
    def __init__(self) -> None:
        self.reset_calls = 0
        self.requeue_calls = []

    def reset_queue(self) -> dict[str, int]:
        self.reset_calls += 1
        return {"issues": 3, "runs": 4}

    def requeue_failed(
        self,
        numbers=None,
        *,
        target_stage: str = "spec_ready",
    ) -> dict[str, object]:
        self.requeue_calls.append((numbers, target_stage))
        return {
            "requeued": 2,
            "numbers": [730, 731],
            "target_stage": target_stage,
        }


class DummyPoller:
    instances = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.instances.append(self)

    async def run_forever(self, stop) -> None:
        stop.set()


def test_async_main_honors_reset_queue_env_before_polling(monkeypatch, capsys) -> None:
    DummyPoller.instances = []
    store = Store()
    cfg = Config(
        target_repo="atvirokodosprendimai/wgmesh", mode="shadow", database_mode="local"
    )
    goose_runner = object()

    monkeypatch.setenv("RESET_QUEUE", "1")
    monkeypatch.setattr(main, "load_config", lambda: cfg)
    monkeypatch.setattr(main, "init_tracing", lambda config: None)
    monkeypatch.setattr(main, "init_scoring", lambda config: None)
    monkeypatch.setattr(main, "open_state_store", lambda config: store)
    monkeypatch.setattr(main, "make_forge", lambda config: object())
    monkeypatch.setattr(main, "build_graph", lambda config: object())
    monkeypatch.setattr(
        main, "build_executor", lambda config: goose_runner, raising=False
    )
    monkeypatch.setattr(main, "Poller", DummyPoller)

    asyncio.run(main.async_main())

    assert store.reset_calls == 1
    assert DummyPoller.instances[0].kwargs["goose_runner"] is goose_runner
    assert "[pipeline] reset_queue cleared issues=3 runs=4" in capsys.readouterr().err


def test_main_reset_queue_flag_requests_reset(monkeypatch) -> None:
    calls = []

    async def fake_async_main(*, reset_queue: bool = False) -> None:
        calls.append(reset_queue)

    monkeypatch.setattr(main, "async_main", fake_async_main)

    main.main(["--reset-queue"])

    assert calls == [True]


def test_main_requeue_failed_runs_one_shot_and_does_not_poll(monkeypatch, capsys) -> None:
    store = Store()
    cfg = Config(
        target_repo="atvirokodosprendimai/wgmesh", mode="shadow", database_mode="local"
    )

    async def fail_async_main(*, reset_queue: bool = False) -> None:
        raise AssertionError("requeue_failed must not enter async_main")

    monkeypatch.setattr(main, "load_config", lambda: cfg)
    monkeypatch.setattr(main, "open_state_store", lambda config: store)
    monkeypatch.setattr(main, "async_main", fail_async_main)

    main.main(["--requeue-failed"])

    assert store.requeue_calls == [(None, "spec_ready")]
    assert (
        "[pipeline] requeue_failed requeued=2 target_stage=spec_ready numbers=[730, 731]"
        in capsys.readouterr().err
    )


def test_main_reset_queue_and_exit_clears_and_does_not_poll(monkeypatch, capsys) -> None:
    store = Store()
    cfg = Config(
        target_repo="atvirokodosprendimai/wgmesh", mode="shadow", database_mode="local"
    )

    async def fail_async_main(*, reset_queue: bool = False) -> None:
        raise AssertionError("--reset-queue-and-exit must not enter async_main")

    monkeypatch.setattr(main, "load_config", lambda: cfg)
    monkeypatch.setattr(main, "open_state_store", lambda config: store)
    monkeypatch.setattr(main, "async_main", fail_async_main)

    main.main(["--reset-queue-and-exit"])

    assert store.reset_calls == 1
    assert (
        "[pipeline] reset_queue_and_exit cleared issues=3 runs=4"
        in capsys.readouterr().err
    )


def test_main_requeue_failed_passes_issue_filter(monkeypatch) -> None:
    store = Store()
    cfg = Config(
        target_repo="atvirokodosprendimai/wgmesh", mode="shadow", database_mode="local"
    )

    monkeypatch.setattr(main, "load_config", lambda: cfg)
    monkeypatch.setattr(main, "open_state_store", lambda config: store)

    main.main(["--requeue-failed", "--issues", "730,731"])

    assert store.requeue_calls == [([730, 731], "spec_ready")]


def test_main_requeue_failed_passes_target_stage(monkeypatch) -> None:
    store = Store()
    cfg = Config(
        target_repo="atvirokodosprendimai/wgmesh", mode="shadow", database_mode="local"
    )

    monkeypatch.setattr(main, "load_config", lambda: cfg)
    monkeypatch.setattr(main, "open_state_store", lambda config: store)

    main.main(["--requeue-failed", "--target-stage", "queued"])

    assert store.requeue_calls == [(None, "queued")]


def test_main_requeue_failed_rejects_malformed_issues_before_running(monkeypatch) -> None:
    calls = []

    def fail_requeue_failed_main(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(main, "requeue_failed_main", fail_requeue_failed_main)

    with pytest.raises(SystemExit) as exc:
        main.main(["--requeue-failed", "--issues", "730,x"])

    assert exc.value.code == 2
    assert calls == []
