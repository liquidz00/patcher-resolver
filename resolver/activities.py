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
async def resolve_to_file(labels: list[str], stamp: str) -> dict:
    return await asyncio.to_thread(resolve.resolve_to_file, labels, stamp)
