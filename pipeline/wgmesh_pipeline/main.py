from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

from wgmesh_pipeline.config import load_config
from wgmesh_pipeline.github.client import GitHubClient
from wgmesh_pipeline.graph.build import build_graph
from wgmesh_pipeline.poller import Poller
from wgmesh_pipeline.scoring import init_scoring
from wgmesh_pipeline.state.store import open_state_store
from wgmesh_pipeline.tracing import init_tracing


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


async def async_main(*, reset_queue: bool = False) -> None:
    config = load_config()
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
    poller = Poller(config=config, store=store, client=GitHubClient(config), graph=build_graph(config))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await poller.run_forever(stop)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset-queue", action="store_true", help="clear durable issue queue and run history before polling")
    args = parser.parse_args(argv)
    asyncio.run(async_main(reset_queue=args.reset_queue))


if __name__ == "__main__":
    main()
