"""
CLI for the resolver.

    python -m resolver.cli run-once                  # resolve the full set now (writes NDJSON)
    python -m resolver.cli run-once --label firefox  # resolve only these label(s)
    python -m resolver.cli schedule                  # create the daily 04:30 UTC schedule
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
from resolver.workflows import ResolveCatalog

_SCHEDULE_ID = "patcher-resolver-daily"


async def _run_once(labels: list[str] | None) -> None:
    settings = get_settings()
    client = await Client.connect(settings.temporal_address)
    result = await client.execute_workflow(
        ResolveCatalog.run,
        labels,
        id=f"resolve-{uuid.uuid4()}",
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
                ResolveCatalog.run,
                None,
                id="resolve-daily",
                task_queue=settings.temporal_task_queue,
            ),
            spec=ScheduleSpec(cron_expressions=["30 4 * * *"]),
        ),
    )
    print(f"Schedule '{_SCHEDULE_ID}' created: ResolveCatalog daily at 04:30 UTC.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="patcher-resolver")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run-once", help="Resolve now (writes NDJSON).")
    run_parser.add_argument(
        "--label",
        dest="labels",
        action="append",
        help="Resolve only this label (repeatable). Omit to resolve the full set.",
    )
    sub.add_parser("schedule", help="Create the daily 04:30 UTC schedule.")

    args = parser.parse_args()
    if args.command == "run-once":
        asyncio.run(_run_once(args.labels))
    elif args.command == "schedule":
        asyncio.run(_schedule())


if __name__ == "__main__":
    main()
