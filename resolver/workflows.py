"""
The resolution workflow.

``ResolveCatalog`` refreshes Installomator, resolves the worklist on the macOS host
(one ``resolve_label`` activity per label, fanned out with the worker capping how
many run at once), writes the results locally, and — unless ``publish`` is False
— POSTs the arm64-canonical values back to the API. Activities are referenced by
name so this module stays free of the subprocess/httpx imports the workflow
sandbox would reject.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

_RETRY = RetryPolicy(maximum_attempts=3)
_LABEL_RETRY = RetryPolicy(maximum_attempts=2)


@workflow.defn
class ResolveCatalog:
    @workflow.run
    async def run(self, labels: list[str] | None = None, publish: bool = True) -> dict:
        head = await workflow.execute_activity(
            "update_installomator",
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=_RETRY,
        )
        if not labels:
            labels = await workflow.execute_activity(
                "fetch_worklist",
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=_RETRY,
            )
        workflow.logger.info("resolving %d labels", len(labels))

        # One activity per label, fanned out; the worker caps how many run at once
        # (settings.concurrency). return_exceptions keeps a label that fails all its
        # retries from sinking the batch — it comes back as an exception we count.
        raw = await asyncio.gather(
            *[
                workflow.execute_activity(
                    "resolve_label",
                    label,
                    start_to_close_timeout=timedelta(minutes=15),
                    retry_policy=_LABEL_RETRY,
                )
                for label in labels
            ],
            return_exceptions=True,
        )
        results = [record for record in raw if not isinstance(record, BaseException)]
        failed = len(raw) - len(results)

        stamp = workflow.now().strftime("%Y%m%dT%H%M%SZ")
        summary = await workflow.execute_activity(
            "write_results",
            args=[results, stamp],
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_RETRY,
        )
        outcome = {"installomator": head, "labels": len(labels), "failed": failed, **summary}

        if publish:
            outcome["ingest"] = await workflow.execute_activity(
                "publish_results",
                results,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=_RETRY,
            )
        workflow.logger.info("run complete: %s", outcome)
        return outcome
