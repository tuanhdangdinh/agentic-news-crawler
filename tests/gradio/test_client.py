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


@pytest.mark.asyncio
async def test_parse_prompt_returns_parsed_fields(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://engine/parse",
        json={"seed_url": "https://cafef.vn", "goal": "finance news"},
    )
    result = await client.parse_prompt("finance news from cafef.vn", base_url="http://engine")
    assert result["seed_url"] == "https://cafef.vn"


@pytest.mark.asyncio
async def test_parse_prompt_raises_on_422(httpx_mock):
    import httpx

    httpx_mock.add_response(
        method="POST",
        url="http://engine/parse",
        status_code=422,
        json={"detail": "no url found"},
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.parse_prompt("vague", base_url="http://engine")


@pytest.mark.asyncio
async def test_get_storage_overview_returns_dict(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="http://engine/storage",
        json={
            "total_files": 2,
            "total_size_bytes": 1024,
            "last_modified": "2026-06-29T10:00:00+00:00",
            "objects": [],
        },
    )
    result = await client.get_storage_overview(base_url="http://engine")
    assert result["total_files"] == 2


@pytest.mark.asyncio
async def test_delete_stored_result_sends_delete(httpx_mock):
    httpx_mock.add_response(
        method="DELETE",
        url="http://engine/storage/abc123",
        status_code=204,
    )
    await client.delete_stored_result("abc123", base_url="http://engine")
