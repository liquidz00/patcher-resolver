"""Temporal activities: thin async wrappers that offload the blocking pipeline to threads."""

import asyncio

from temporalio import activity

from resolver import resolve


@activity.defn
async def update_installomator() -> str:
    return await asyncio.to_thread(resolve.update_installomator)


@activity.defn
async def fetch_worklist() -> list[str]:
    return await asyncio.to_thread(resolve.fetch_worklist)


@activity.defn
async def resolve_label(label: str) -> dict:
    activity.logger.info("resolving %s", label)
    return await asyncio.to_thread(resolve.resolve_label, label)


@activity.defn
async def write_results(results: list[dict], stamp: str) -> dict:
    return await asyncio.to_thread(resolve.write_results, results, stamp)


@activity.defn
async def publish_results(results: list[dict]) -> dict:
    return await asyncio.to_thread(resolve.publish_results, results)
