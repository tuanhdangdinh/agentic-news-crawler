"""Tests for the Gradio crawl interface backend."""

from __future__ import annotations

import httpx
import pytest

from crawl_tool.gradio import ui_shared as ui


def _async_return(value):
    async def _fn(*args, **kwargs):
        return value

    return _fn


def test_parse_patterns_removes_blank_lines_and_whitespace():
    assert ui._parse_patterns("  *article*\n\n *video*  ") == [
        "*article*",
        "*video*",
    ]


def test_build_request_parses_schema_and_controls():
    request = ui._build_request(
        "https://cafef.vn",
        " collect news ",
        " extract title ",
        '{"type": "object", "properties": {}}',
        2,
        5,
        1000,
        False,
        "*article*\n*news*",
        "*video*",
        " last 7 days ",
        False,
        " article ",
        8000,
    )

    assert request == {
        "seed_url": "https://cafef.vn",
        "goal": "collect news",
        "extract_prompt": "extract title",
        "extract_schema": {"type": "object", "properties": {}},
        "max_depth": 2,
        "max_pages": 5,
        "token_budget": 1000,
        "same_domain": False,
        "include_patterns": ["*article*", "*news*"],
        "exclude_patterns": ["*video*"],
        "date_filter": "last 7 days",
        "include_undated": False,
        "css_selector": "article",
        "max_chars": 8000,
    }


@pytest.mark.asyncio
async def test_run_crawl_polls_then_renders(monkeypatch, tmp_path):
    payload = {
        "meta": {"total_pages": 1, "successful": 1, "failed": 0},
        "pages": [],
    }

    async def fake_poll(job_id, **kwargs):
        assert job_id == "job1"
        yield {"status": "running", "progress": {"pages_collected": 0}}
        yield {"status": "done", "payload": payload}

    output_path = tmp_path / "out.json"
    monkeypatch.setattr(ui, "start_crawl", _async_return("job1"))
    monkeypatch.setattr(ui, "poll_until_done", fake_poll)
    monkeypatch.setattr(ui, "download_result", _async_return(b"{}"))
    monkeypatch.setattr(ui, "_output_path", lambda fmt: str(output_path))

    frames = [
        frame
        async for frame in ui.run_crawl(
            "https://cafef.vn",
            "collect news",
            "",
            "",
            1,
            5,
            500_000,
            True,
            "",
            "",
            "",
            False,
            "",
            0,
            "json",
        )
    ]

    statuses = [frame[0] for frame in frames]
    assert any("Running" in status for status in statuses)
    assert "Collected 1 page" in statuses[-1]
    assert frames[-1][2] == payload
    assert frames[-1][5] == str(output_path)
    assert output_path.read_bytes() == b"{}"


@pytest.mark.asyncio
async def test_run_crawl_surfaces_start_error(monkeypatch):
    request = httpx.Request("POST", "http://engine/crawl")
    error = httpx.ConnectError("unreachable", request=request)

    async def raise_error(*args, **kwargs):
        raise error

    monkeypatch.setattr(ui, "start_crawl", raise_error)

    frames = [
        frame
        async for frame in ui.run_crawl(
            "https://cafef.vn",
            "",
            "",
            "",
            1,
            5,
            500_000,
            True,
            "",
            "",
            "",
            True,
            "",
            0,
            "json",
        )
    ]

    assert frames[0][0] == "Engine error: unreachable"


@pytest.mark.asyncio
async def test_run_crawl_surfaces_terminal_job_error(monkeypatch):
    async def fake_poll(job_id, **kwargs):
        yield {"status": "error", "error": "boom"}

    monkeypatch.setattr(ui, "start_crawl", _async_return("job1"))
    monkeypatch.setattr(ui, "poll_until_done", fake_poll)

    frames = [
        frame
        async for frame in ui.run_crawl(
            "https://cafef.vn",
            "",
            "",
            "",
            1,
            5,
            500_000,
            True,
            "",
            "",
            "",
            True,
            "",
            0,
            "json",
        )
    ]

    assert frames[0][0] == "Crawl failed: boom"


def test_nav_updates_shows_only_selected():
    from crawl_tool.gradio.app import _nav_updates

    updates = _nav_updates("Advanced Crawl")
    # First 3: page visibility
    assert updates[0]["visible"] is False  # Quick Crawl hidden
    assert updates[1]["visible"] is True   # Advanced Crawl shown
    assert updates[2]["visible"] is False  # Storage hidden
    # Next 3: button classes
    assert "nav-btn-active" not in updates[3]["elem_classes"]
    assert "nav-btn-active" in updates[4]["elem_classes"]
    assert "nav-btn-active" not in updates[5]["elem_classes"]
    assert updates[2]["visible"] is False  # Storage hidden
