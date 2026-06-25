"""Tests for engine/query.py — _execute_query."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from crawl_tool.engine.contract import CrawlQuery
from crawl_tool.engine.query import _execute_query


def _write_fixture(path: Path, job_id: str, seed_url: str, goal: str, generated_at: str) -> None:
    payload = {
        "meta": {
            "job_id": job_id,
            "seed_url": seed_url,
            "goal": goal,
            "generated_at": generated_at,
            "total_pages": 5,
            "successful": 4,
            "failed": 1,
        },
        "pages": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _conn() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def test_execute_query_returns_all_when_no_filters(tmp_path):
    _write_fixture(tmp_path / "crawl-a.json", "a", "https://vnexpress.net", "news", "2026-06-20T10:00:00Z")
    _write_fixture(tmp_path / "crawl-b.json", "b", "https://cafef.vn", "finance", "2026-06-21T10:00:00Z")
    path = str(tmp_path / "crawl-*.json")
    rows = _execute_query(_conn(), path, CrawlQuery())
    assert len(rows) == 2
    job_ids = {r["job_id"] for r in rows}
    assert job_ids == {"a", "b"}


def test_execute_query_filters_by_seed_url(tmp_path):
    _write_fixture(tmp_path / "crawl-a.json", "a", "https://vnexpress.net", "news", "2026-06-20T10:00:00Z")
    _write_fixture(tmp_path / "crawl-b.json", "b", "https://cafef.vn", "finance", "2026-06-21T10:00:00Z")
    path = str(tmp_path / "crawl-*.json")
    rows = _execute_query(_conn(), path, CrawlQuery(seed_url="cafef"))
    assert len(rows) == 1
    assert rows[0]["job_id"] == "b"


def test_execute_query_filters_by_goal(tmp_path):
    _write_fixture(tmp_path / "crawl-a.json", "a", "https://vnexpress.net", "economy news", "2026-06-20T10:00:00Z")
    _write_fixture(tmp_path / "crawl-b.json", "b", "https://cafef.vn", "stock prices", "2026-06-21T10:00:00Z")
    path = str(tmp_path / "crawl-*.json")
    rows = _execute_query(_conn(), path, CrawlQuery(goal="economy"))
    assert len(rows) == 1
    assert rows[0]["job_id"] == "a"


def test_execute_query_filters_by_date_range(tmp_path):
    _write_fixture(tmp_path / "crawl-a.json", "a", "https://example.com", "", "2026-06-19T10:00:00Z")
    _write_fixture(tmp_path / "crawl-b.json", "b", "https://example.com", "", "2026-06-21T10:00:00Z")
    _write_fixture(tmp_path / "crawl-c.json", "c", "https://example.com", "", "2026-06-23T10:00:00Z")
    path = str(tmp_path / "crawl-*.json")
    rows = _execute_query(_conn(), path, CrawlQuery(date_from="2026-06-20", date_to="2026-06-22"))
    assert len(rows) == 1
    assert rows[0]["job_id"] == "b"


def test_execute_query_respects_limit(tmp_path):
    for i in range(5):
        _write_fixture(
            tmp_path / f"crawl-{i}.json", str(i), "https://example.com", "", "2026-06-20T10:00:00Z"
        )
    path = str(tmp_path / "crawl-*.json")
    rows = _execute_query(_conn(), path, CrawlQuery(limit=2))
    assert len(rows) == 2


def test_execute_query_returns_empty_for_no_match(tmp_path):
    _write_fixture(tmp_path / "crawl-a.json", "a", "https://vnexpress.net", "news", "2026-06-20T10:00:00Z")
    path = str(tmp_path / "crawl-*.json")
    rows = _execute_query(_conn(), path, CrawlQuery(seed_url="nytimes"))
    assert rows == []


def test_execute_query_returns_correct_fields(tmp_path):
    _write_fixture(tmp_path / "crawl-a.json", "abc", "https://test.com", "my goal", "2026-06-20T10:00:00Z")
    path = str(tmp_path / "crawl-*.json")
    rows = _execute_query(_conn(), path, CrawlQuery())
    assert rows[0] == {
        "job_id": "abc",
        "seed_url": "https://test.com",
        "goal": "my goal",
        "generated_at": "2026-06-20T10:00:00Z",
        "total_pages": 5,
        "successful": 4,
        "failed": 1,
    }
