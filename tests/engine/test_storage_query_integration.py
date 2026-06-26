"""Integration tests for the MinIO storage + DuckDB query pipeline.

Requires Docker to be running. Spins up a real MinIO container via
testcontainers and exercises the full put_result → run_query → get_result
cycle against live S3 API calls.

Run with:
    uv run python -m pytest -m integration tests/engine/test_storage_query_integration.py -v
"""

from __future__ import annotations

import json

import pytest
from testcontainers.minio import MinioContainer

import docker
from crawl_tool.engine.contract import CrawlQuery
from crawl_tool.engine.query import run_query
from crawl_tool.engine.storage import StorageSettings, get_result, put_result

BUCKET = "crawl-results-test"


def _docker_available() -> bool:
    try:
        docker.from_env().version()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _docker_available(), reason="Docker daemon not running"),
]

_PAYLOAD_A = {
    "meta": {
        "seed_url": "https://vietnamnet.vn",
        "goal": "finance news",
        "generated_at": "2026-06-20T08:00:00Z",
        "total_pages": 3,
        "successful": 3,
        "failed": 0,
    },
    "pages": [{"url": "https://vietnamnet.vn/article-1"}],
}

_PAYLOAD_B = {
    "meta": {
        "seed_url": "https://cafef.vn",
        "goal": "stock market update",
        "generated_at": "2026-06-22T10:00:00Z",
        "total_pages": 5,
        "successful": 4,
        "failed": 1,
    },
    "pages": [{"url": "https://cafef.vn/article-2"}],
}


@pytest.fixture(scope="module")
def minio_settings():
    """Start a MinIO container, create the test bucket, and yield StorageSettings."""
    from minio import Minio

    with MinioContainer() as minio:
        host = minio.get_container_host_ip()
        port = minio.get_exposed_port(9000)
        client = Minio(
            f"{host}:{port}",
            access_key=minio.access_key,
            secret_key=minio.secret_key,
            secure=False,
        )
        client.make_bucket(BUCKET)
        yield StorageSettings(
            endpoint=f"{host}:{port}",
            access_key=minio.access_key,
            secret_key=minio.secret_key,
            bucket=BUCKET,
            secure=False,
        )


@pytest.mark.asyncio
async def test_put_then_get_roundtrip(minio_settings):
    """put_result stores the file; get_result retrieves identical bytes."""
    await put_result("job-rt-001", _PAYLOAD_A, minio_settings)
    raw = await get_result("job-rt-001", minio_settings)
    assert raw is not None
    stored = json.loads(raw)
    assert stored["meta"]["job_id"] == "job-rt-001"
    assert stored["meta"]["seed_url"] == "https://vietnamnet.vn"
    assert stored["pages"] == _PAYLOAD_A["pages"]


@pytest.mark.asyncio
async def test_put_does_not_mutate_original_payload(minio_settings):
    """put_result injects job_id into storage without modifying the caller's dict."""
    payload = {
        "meta": {
            "seed_url": "https://example.com",
            "goal": "test goal",
            "generated_at": "2026-06-25T00:00:00Z",
            "total_pages": 1,
            "successful": 1,
            "failed": 0,
        },
        "pages": [],
    }
    await put_result("job-mut-001", payload, minio_settings)
    assert "job_id" not in payload["meta"]


@pytest.mark.asyncio
async def test_get_result_returns_none_for_missing_key(minio_settings):
    """get_result returns None when the requested job_id does not exist in MinIO."""
    result = await get_result("job-does-not-exist", minio_settings)
    assert result is None


@pytest.mark.asyncio
async def test_run_query_returns_empty_on_fresh_bucket(minio_settings):
    """run_query returns [] when the bucket has no files matching the glob."""
    empty_settings = StorageSettings(
        endpoint=minio_settings.endpoint,
        access_key=minio_settings.access_key,
        secret_key=minio_settings.secret_key,
        bucket="empty-bucket-xyz",
        secure=False,
    )
    results = await run_query(CrawlQuery(), empty_settings)
    assert results == []


@pytest.mark.asyncio
async def test_run_query_returns_uploaded_results(minio_settings):
    """run_query over MinIO returns all uploaded crawl summaries."""
    await put_result("job-q-001", _PAYLOAD_A, minio_settings)
    await put_result("job-q-002", _PAYLOAD_B, minio_settings)

    results = await run_query(CrawlQuery(limit=50), minio_settings)
    job_ids = {r.job_id for r in results}
    assert "job-q-001" in job_ids
    assert "job-q-002" in job_ids


@pytest.mark.asyncio
async def test_run_query_filters_by_seed_url(minio_settings):
    """run_query seed_url filter returns only matching records."""
    await put_result("job-f-001", _PAYLOAD_A, minio_settings)
    await put_result("job-f-002", _PAYLOAD_B, minio_settings)

    results = await run_query(CrawlQuery(seed_url="vietnamnet"), minio_settings)
    assert all("vietnamnet" in r.seed_url for r in results)
    assert any(r.job_id == "job-f-001" for r in results)
    assert all(r.job_id != "job-f-002" for r in results)


@pytest.mark.asyncio
async def test_run_query_filters_by_date_range(minio_settings):
    """run_query date_from/date_to filter excludes records outside the range."""
    await put_result("job-d-001", _PAYLOAD_A, minio_settings)  # 2026-06-20
    await put_result("job-d-002", _PAYLOAD_B, minio_settings)  # 2026-06-22

    results = await run_query(
        CrawlQuery(date_from="2026-06-21", date_to="2026-06-23", limit=50), minio_settings
    )
    job_ids = {r.job_id for r in results}
    assert "job-d-002" in job_ids
    assert "job-d-001" not in job_ids


@pytest.mark.asyncio
async def test_run_query_summary_fields_match_payload(minio_settings):
    """CrawlSummary fields returned by run_query match the stored payload meta."""
    await put_result("job-s-001", _PAYLOAD_A, minio_settings)

    results = await run_query(CrawlQuery(seed_url="vietnamnet.vn"), minio_settings)
    match = next((r for r in results if r.job_id == "job-s-001"), None)
    assert match is not None
    assert match.seed_url == "https://vietnamnet.vn"
    assert match.goal == "finance news"
    assert match.total_pages == 3
    assert match.successful == 3
    assert match.failed == 0
    assert match.generated_at == "2026-06-20T08:00:00Z"
