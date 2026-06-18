"""Tests for crawl_gradio.client."""

from __future__ import annotations

import pytest

from crawl_tool.gradio import client


@pytest.mark.asyncio
async def test_start_crawl_posts_and_returns_job_id(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://engine/crawl",
        json={"job_id": "abc"},
    )

    job_id = await client.start_crawl(
        {"seed_url": "https://a"},
        base_url="http://engine",
    )

    assert job_id == "abc"


@pytest.mark.asyncio
async def test_poll_until_done_yields_until_terminal(httpx_mock):
    httpx_mock.add_response(
        url="http://engine/crawl/abc",
        json={"status": "running", "progress": {"pages_collected": 1}},
    )
    httpx_mock.add_response(
        url="http://engine/crawl/abc",
        json={"status": "done", "payload": {"meta": {}, "pages": []}},
    )

    seen = [
        status["status"]
        async for status in client.poll_until_done(
            "abc",
            base_url="http://engine",
            interval=0,
        )
    ]

    assert seen == ["running", "done"]


@pytest.mark.asyncio
async def test_download_result_returns_bytes(httpx_mock):
    httpx_mock.add_response(
        url="http://engine/crawl/abc/result?format=json",
        content=b"{}",
    )

    data = await client.download_result(
        "abc",
        "json",
        base_url="http://engine",
    )

    assert data == b"{}"
