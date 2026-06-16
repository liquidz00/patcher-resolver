"""
CLI for the shadow resolver.

    python -m resolver.cli run-once    # run a resolution now (writes NDJSON, no POST)
    python -m resolver.cli schedule    # daily schedule at 04:30 UTC (before the GitHub job)
"""

import argparse
import asyncio
import uuid

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleSpec,
)

from resolver.config import get_settings
from resolver.workflows import ShadowResolve

_SCHEDULE_ID = "patcher-resolver-shadow"


async def _run_once() -> None:
    settings = get_settings()
    client = await Client.connect(settings.temporal_address)
    result = await client.execute_workflow(
        ShadowResolve.run,
        id=f"shadow-resolve-{uuid.uuid4()}",
        task_queue=settings.temporal_task_queue,
    )
    print(result)


async def _schedule() -> None:
    settings = get_settings()
    client = await Client.connect(settings.temporal_address)
    await client.create_schedule(
        _SCHEDULE_ID,
        Schedule(
            action=ScheduleActionStartWorkflow(
                ShadowResolve.run,
                id="shadow-resolve",
                task_queue=settings.temporal_task_queue,
            ),
            spec=ScheduleSpec(cron_expressions=["30 4 * * *"]),
        ),
    )
    print(f"Schedule '{_SCHEDULE_ID}' created: ShadowResolve daily at 04:30 UTC.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="patcher-resolver")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run-once", help="Resolve now (writes NDJSON, no POST).")
    sub.add_parser("schedule", help="Create the daily 04:30 UTC schedule.")

    args = parser.parse_args()
    if args.command == "run-once":
        asyncio.run(_run_once())
    elif args.command == "schedule":
        asyncio.run(_schedule())


if __name__ == "__main__":
    main()
