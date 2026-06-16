"""Temporal worker: registers the workflow and activities, then serves."""

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from resolver import activities
from resolver.config import get_settings
from resolver.workflows import ShadowResolve


async def main() -> None:
    settings = get_settings()
    client = await Client.connect(settings.temporal_address)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[ShadowResolve],
        activities=[
            activities.update_installomator,
            activities.fetch_worklist,
            activities.resolve_to_file,
        ],
    )
    print(f"patcher-resolver worker listening on task queue '{settings.temporal_task_queue}'")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
