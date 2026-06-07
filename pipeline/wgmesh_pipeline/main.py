from __future__ import annotations

import asyncio
import signal
from pathlib import Path

from wgmesh_pipeline.config import load_config
from wgmesh_pipeline.github.client import GitHubClient
from wgmesh_pipeline.graph.build import build_graph
from wgmesh_pipeline.poller import Poller
from wgmesh_pipeline.state.store import StateStore
from wgmesh_pipeline.tracing import init_tracing


async def async_main() -> None:
    config = load_config()
    init_tracing(config)
    db_path = Path(config.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = StateStore(db_path)
    poller = Poller(config=config, store=store, client=GitHubClient(config), graph=build_graph(config))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await poller.run_forever(stop)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

