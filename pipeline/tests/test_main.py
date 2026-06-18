from __future__ import annotations

import asyncio

from wgmesh_pipeline import main
from wgmesh_pipeline.config import Config


class Store:
    def __init__(self) -> None:
        self.reset_calls = 0

    def reset_queue(self) -> dict[str, int]:
        self.reset_calls += 1
        return {"issues": 3, "runs": 4}


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
