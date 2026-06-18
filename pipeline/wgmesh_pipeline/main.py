from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from wgmesh_pipeline.config import load_config
from wgmesh_pipeline.control_loop import ControlLoopScheduler
from wgmesh_pipeline.forge.factory import make_forge
from wgmesh_pipeline.forge.gitfacts import make_resolution_lookup
from wgmesh_pipeline.executor import build_executor
from wgmesh_pipeline.goose.runner import GooseRunner  # noqa: F401 — kept for downstream compat
from wgmesh_pipeline.graph.build import build_graph
from wgmesh_pipeline.poller import Poller
from wgmesh_pipeline.scoring import init_scoring
from wgmesh_pipeline.state.store import open_state_store
from wgmesh_pipeline.tracing import init_tracing


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


async def async_main(*, reset_queue: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
        force=True,
    )
    config = load_config()
    logging.getLogger("wgmesh_pipeline").info(
        "starting: mode=%s database_mode=%s poll_interval=%ss executor=%s",
        config.mode, config.database_mode, config.poll_interval_seconds, config.executor,
    )
    init_tracing(config)
    init_scoring(config)
    if config.database_mode == "local":
        db_path = Path(config.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
    store = open_state_store(config)
    if reset_queue or _truthy(os.environ.get("RESET_QUEUE")):
        cleared = store.reset_queue()
        print(
            f"[pipeline] reset_queue cleared issues={cleared['issues']} runs={cleared['runs']}",
            file=sys.stderr,
        )
    client = make_forge(config)
    poller = Poller(
        config=config,
        store=store,
        client=client,
        resolution_lookup=make_resolution_lookup(config.repo_path, client),
        graph=build_graph(config),
        goose_runner=build_executor(config),
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    if config.control_loop_enabled:
        scheduler = ControlLoopScheduler(config=config, forge=client, store=store)
        logging.getLogger("wgmesh_pipeline").info(
            "control loop enabled (mode=%s, shadow-only) — running concurrently with poller",
            config.control_loop_mode,
        )
        await asyncio.gather(poller.run_forever(stop), scheduler.run(stop))
    else:
        await poller.run_forever(stop)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset-queue", action="store_true", help="clear durable issue queue and run history before polling")
    args = parser.parse_args(argv)
    asyncio.run(async_main(reset_queue=args.reset_queue))


if __name__ == "__main__":
    main()
