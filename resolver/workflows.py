"""
The resolution workflow.

``ShadowResolve`` refreshes Installomator, fetches the worklist, resolves it on
this Mac, and writes the NDJSON locally (shadow mode: no POST). Activities are
referenced by name so this module stays free of the httpx/subprocess imports the
workflow sandbox would reject.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

_RETRY = RetryPolicy(maximum_attempts=3)


@workflow.defn
class ShadowResolve:
    @workflow.run
    async def run(self) -> dict:
        head = await workflow.execute_activity(
            "update_installomator",
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=_RETRY,
        )
        labels = await workflow.execute_activity(
            "fetch_worklist",
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_RETRY,
        )
        # Resolution shells out to resolveLabel.sh and hits the network per label,
        # so it can run for many minutes; mirror the GitHub job's 2h ceiling and
        # don't retry a long job aggressively. The activity writes the NDJSON to
        # disk and returns only a path + count (the blob stays out of history).
        stamp = workflow.now().strftime("%Y%m%dT%H%M%SZ")
        result = await workflow.execute_activity(
            "resolve_to_file",
            args=[labels, stamp],
            start_to_close_timeout=timedelta(hours=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return {"installomator": head, "worklist": len(labels), **result}
