"""Tests for crawl_engine.contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crawl_tool.engine.config import AgentConfig
from crawl_tool.engine.contract import CrawlRequest, JobProgress, JobResult, JobStatus


def test_crawl_request_maps_to_agent_config():
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    request = CrawlRequest(
        seed_url="https://cafef.vn",
        goal="news",
        extract_prompt="Extract the headline",
        extract_schema=schema,
        max_depth=2,
        max_pages=25,
        token_budget=125_000,
        same_domain=False,
        include_patterns=["/news/*"],
        exclude_patterns=["/video/*"],
        date_filter="last 7 days",
        include_undated=False,
        css_selector="article",
        max_chars=10_000,
    )

    config = request.to_agent_config()

    assert isinstance(config, AgentConfig)
    assert config.goal == "news"
    assert config.extract_prompt == "Extract the headline"
    assert config.extract_schema == schema
    assert config.max_depth == 2
    assert config.max_pages == 25
    assert config.token_budget == 125_000
    assert config.same_domain is False
    assert config.include_patterns == ["/news/*"]
    assert config.exclude_patterns == ["/video/*"]
    assert config.date_filter == "last 7 days"
    assert config.include_undated is False
    assert config.css_selector == "article"
    assert config.max_chars == 10_000


def test_crawl_request_rejects_depth_above_ceiling():
    with pytest.raises(ValidationError):
        CrawlRequest(seed_url="https://cafef.vn", max_depth=6)


def test_crawl_request_requires_seed_url():
    with pytest.raises(ValidationError):
        CrawlRequest()


def test_crawl_request_allows_prompt_only():
    request = CrawlRequest(prompt="crawl vnexpress.net for tech news")
    assert request.seed_url == ""
    assert request.prompt == "crawl vnexpress.net for tech news"


def test_crawl_request_requires_seed_url_or_prompt():
    with pytest.raises(ValidationError):
        CrawlRequest()


def test_job_result_defaults_to_zero_progress():
    result = JobResult(status=JobStatus.running)
    assert result.progress == JobProgress(pages_collected=0)
    assert result.payload is None


def test_parse_request_requires_prompt():
    from pydantic import ValidationError

    from crawl_tool.engine.contract import ParseRequest

    with pytest.raises(ValidationError):
        ParseRequest()


def test_parse_request_accepts_prompt():
    from crawl_tool.engine.contract import ParseRequest

    req = ParseRequest(prompt="get news from cafef.vn")
    assert req.prompt == "get news from cafef.vn"


def test_storage_overview_defaults():
    from crawl_tool.engine.contract import StorageOverview

    ov = StorageOverview(
        total_files=0, total_size_bytes=0, last_modified=None, objects=[]
    )
    assert ov.total_files == 0
    assert ov.objects == []
