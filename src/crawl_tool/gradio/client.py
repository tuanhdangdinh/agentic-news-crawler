"""Async HTTP client for the crawl engine."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import httpx

ENGINE_URL = os.environ.get("ENGINE_URL", "http://localhost:8000")
POLL_SECONDS = 2.0


async def start_crawl(request: dict, *, base_url: str = ENGINE_URL) -> str:
    """Start a crawl and return its job identifier.

    Args:
        request: Crawl request payload.
        base_url: Crawl engine base URL.

    Returns:
        Created crawl job identifier.
    """
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        response = await http.post("/crawl", json=request)
        response.raise_for_status()
        return response.json()["job_id"]


async def get_status(job_id: str, *, base_url: str = ENGINE_URL) -> dict:
    """Fetch the current status of a crawl job.

    Args:
        job_id: Crawl job identifier.
        base_url: Crawl engine base URL.

    Returns:
        Current job status payload.
    """
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        response = await http.get(f"/crawl/{job_id}")
        response.raise_for_status()
        return response.json()


async def poll_until_done(
    job_id: str,
    *,
    base_url: str = ENGINE_URL,
    interval: float = POLL_SECONDS,
) -> AsyncIterator[dict]:
    """Yield job statuses until the crawl reaches a terminal state.

    Args:
        job_id: Crawl job identifier.
        base_url: Crawl engine base URL.
        interval: Seconds between status requests.

    Yields:
        Current job status payload.
    """
    while True:
        status = await get_status(job_id, base_url=base_url)
        yield status
        if status["status"] in ("done", "error"):
            return
        await asyncio.sleep(interval)


async def download_result(
    job_id: str,
    fmt: str = "json",
    *,
    base_url: str = ENGINE_URL,
) -> bytes:
    """Download a completed crawl result.

    Args:
        job_id: Crawl job identifier.
        fmt: Requested result format.
        base_url: Crawl engine base URL.

    Returns:
        Serialized result bytes.
    """
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as http:
        response = await http.get(
            f"/crawl/{job_id}/result",
            params={"format": fmt},
        )
        response.raise_for_status()
        return response.content
