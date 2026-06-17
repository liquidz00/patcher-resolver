"""Temporal worker: registers the workflow and activities, then serves."""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from resolver import activities
from resolver.config import get_settings
from resolver.workflows import ResolveCatalog


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    client = await Client.connect(settings.temporal_address)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[ResolveCatalog],
        activities=[
            activities.update_installomator,
            activities.fetch_worklist,
            activities.resolve_label,
            activities.write_results,
            activities.publish_results,
        ],
        max_concurrent_activities=settings.concurrency,
    )
    print(f"patcher-resolver worker listening on task queue '{settings.temporal_task_queue}'")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
