"""Tests for crawl_engine.service via an in-process ASGI client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from crawl_tool.engine.agent import CrawlState
from crawl_tool.engine.models import PageResult
from crawl_tool.engine.prompt_parser import PromptParseError
from crawl_tool.engine.service import JOB_TTL_SECONDS, create_app

_PAYLOAD = {
    "meta": {"total_pages": 1, "successful": 1, "failed": 0},
    "pages": [{"url": "https://a"}],
}


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


async def _poll_until_status(
    client: httpx.AsyncClient,
    job_id: str,
    expected: set[str],
) -> dict:
    for _ in range(100):
        body = (await client.get(f"/crawl/{job_id}")).json()
        if body["status"] in expected:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError(f"job did not reach one of {expected}")


async def _poll_until_terminal(client: httpx.AsyncClient, job_id: str) -> dict:
    return await _poll_until_status(client, job_id, {"done", "error"})


@pytest.mark.asyncio
async def test_healthz_ok():
    async with _client(create_app()) as client:
        resp = await client.get("/healthz")
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_crawl_job_runs_to_done_and_returns_payload():
    app = create_app()
    with patch("crawl_tool.engine.service.execute", AsyncMock(return_value=_PAYLOAD)):
        async with _client(app) as client:
            created = (await client.post("/crawl", json={"seed_url": "https://a"})).json()
            body = await _poll_until_terminal(client, created["job_id"])
    assert body["status"] == "done"
    assert body["payload"]["meta"]["total_pages"] == 1


@pytest.mark.asyncio
async def test_crawl_with_prompt_only_uses_parsed_seed_url():
    app = create_app()
    parsed = {"seed_url": "https://parsed.example"}
    with (
        patch("crawl_tool.engine.service.parse_crawl_prompt", AsyncMock(return_value=parsed)),
        patch(
            "crawl_tool.engine.service.execute", AsyncMock(return_value=_PAYLOAD)
        ) as mock_execute,
    ):
        async with _client(app) as client:
            created = (await client.post("/crawl", json={"prompt": "crawl something"})).json()
            await _poll_until_terminal(client, created["job_id"])
    request = mock_execute.call_args.args[0]
    assert request.seed_url == "https://parsed.example"


@pytest.mark.asyncio
async def test_crawl_with_prompt_and_explicit_field_keeps_explicit():
    app = create_app()
    parsed = {"seed_url": "https://parsed.example", "max_pages": 999}
    with (
        patch("crawl_tool.engine.service.parse_crawl_prompt", AsyncMock(return_value=parsed)),
        patch(
            "crawl_tool.engine.service.execute", AsyncMock(return_value=_PAYLOAD)
        ) as mock_execute,
    ):
        async with _client(app) as client:
            created = (
                await client.post("/crawl", json={"prompt": "crawl something", "max_pages": 20})
            ).json()
            await _poll_until_terminal(client, created["job_id"])
    request = mock_execute.call_args.args[0]
    assert request.max_pages == 20


@pytest.mark.asyncio
async def test_crawl_without_seed_url_or_prompt_returns_422():
    async with _client(create_app()) as client:
        resp = await client.post("/crawl", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_crawl_prompt_with_no_seed_url_found_returns_400():
    app = create_app()
    with patch(
        "crawl_tool.engine.service.parse_crawl_prompt", AsyncMock(return_value={"goal": "x"})
    ):
        async with _client(app) as client:
            resp = await client.post("/crawl", json={"prompt": "collect tech news"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_crawl_prompt_parse_failure_returns_400():
    app = create_app()
    with patch(
        "crawl_tool.engine.service.parse_crawl_prompt",
        AsyncMock(side_effect=PromptParseError("boom")),
    ):
        async with _client(app) as client:
            resp = await client.post("/crawl", json={"prompt": "???"})
    assert resp.status_code == 400
    assert "boom" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_crawl_job_records_error():
    app = create_app()
    with patch("crawl_tool.engine.service.execute", AsyncMock(side_effect=RuntimeError("boom"))):
        async with _client(app) as client:
            created = (await client.post("/crawl", json={"seed_url": "https://a"})).json()
            body = await _poll_until_terminal(client, created["job_id"])
    assert body["status"] == "error"
    assert "boom" in body["error"]


@pytest.mark.asyncio
async def test_unknown_job_returns_404():
    async with _client(create_app()) as client:
        resp = await client.get("/crawl/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_invalid_request_returns_422():
    async with _client(create_app()) as client:
        resp = await client.post(
            "/crawl",
            json={"seed_url": "https://a", "max_depth": 6},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_result_download_json_and_jsonl():
    app = create_app()
    with patch("crawl_tool.engine.service.execute", AsyncMock(return_value=_PAYLOAD)):
        async with _client(app) as client:
            created = (await client.post("/crawl", json={"seed_url": "https://a"})).json()
            await _poll_until_terminal(client, created["job_id"])
            job_id = created["job_id"]
            json_response = await client.get(
                f"/crawl/{job_id}/result",
                params={"format": "json"},
            )
            jsonl_response = await client.get(
                f"/crawl/{job_id}/result",
                params={"format": "jsonl"},
            )
    assert json_response.status_code == 200
    assert json_response.json()["meta"]["total_pages"] == 1
    assert json_response.headers["content-type"].startswith("application/json")
    assert jsonl_response.status_code == 200
    assert jsonl_response.text.strip().startswith("{")
    assert jsonl_response.headers["content-type"].startswith("application/x-ndjson")


@pytest.mark.asyncio
async def test_result_unavailable_while_running():
    app = create_app()
    gate = asyncio.Event()

    async def slow(request, state):
        await gate.wait()
        return _PAYLOAD

    with patch("crawl_tool.engine.service.execute", slow):
        async with _client(app) as client:
            created = (await client.post("/crawl", json={"seed_url": "https://a"})).json()
            await _poll_until_status(client, created["job_id"], {"running"})
            resp = await client.get(f"/crawl/{created['job_id']}/result")
            gate.set()
            await _poll_until_terminal(client, created["job_id"])
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_crawl_jobs_execute_serially():
    app = create_app()
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    calls = 0

    async def controlled_execute(request, state):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            await release_first.wait()
        else:
            second_started.set()
        return _PAYLOAD

    with patch("crawl_tool.engine.service.execute", controlled_execute):
        async with _client(app) as client:
            first = (await client.post("/crawl", json={"seed_url": "https://a"})).json()
            second = (await client.post("/crawl", json={"seed_url": "https://b"})).json()
            await asyncio.wait_for(first_started.wait(), timeout=1)
            await asyncio.sleep(0)
            assert not second_started.is_set()
            second_body = await client.get(f"/crawl/{second['job_id']}")
            assert second_body.json()["status"] == "queued"
            release_first.set()
            await _poll_until_terminal(client, first["job_id"])
            await _poll_until_terminal(client, second["job_id"])
    assert second_started.is_set()


@pytest.mark.asyncio
async def test_running_job_reports_live_pages_collected():
    app = create_app()
    page_added = asyncio.Event()
    release = asyncio.Event()

    async def update_state(request, state: CrawlState):
        state.pages.append(
            PageResult(
                url="https://a",
                final_url="https://a",
                status_code=200,
                title="A",
                markdown="body",
                links_internal=[],
                success=True,
            )
        )
        page_added.set()
        await release.wait()
        return _PAYLOAD

    with patch("crawl_tool.engine.service.execute", update_state):
        async with _client(app) as client:
            created = (await client.post("/crawl", json={"seed_url": "https://a"})).json()
            await asyncio.wait_for(page_added.wait(), timeout=1)
            body = (await client.get(f"/crawl/{created['job_id']}")).json()
            release.set()
            await _poll_until_terminal(client, created["job_id"])
    assert body["status"] == "running"
    assert body["progress"]["pages_collected"] == 1


@pytest.mark.asyncio
async def test_cors_allow_origins_parses_comma_separated_environment(monkeypatch):
    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS",
        "https://one.example,https://two.example",
    )
    async with _client(create_app()) as client:
        response = await client.options(
            "/crawl",
            headers={
                "Origin": "https://two.example",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://two.example"


@pytest.mark.asyncio
async def test_terminal_jobs_are_purged_after_ttl(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("crawl_tool.engine.service._monotonic", lambda: now[0])
    app = create_app()

    with patch("crawl_tool.engine.service.execute", AsyncMock(return_value=_PAYLOAD)):
        async with _client(app) as client:
            first = (await client.post("/crawl", json={"seed_url": "https://a"})).json()
            await _poll_until_terminal(client, first["job_id"])
            now[0] += JOB_TTL_SECONDS + 1
            second = (await client.post("/crawl", json={"seed_url": "https://b"})).json()
            expired = await client.get(f"/crawl/{first['job_id']}")
            await _poll_until_terminal(client, second["job_id"])
    assert expired.status_code == 404


@pytest.mark.asyncio
async def test_query_returns_503_when_storage_disabled():
    app = create_app()
    async with _client(app) as client:
        resp = await client.post("/query", json={})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_storage_endpoint_returns_503_when_storage_disabled():
    app = create_app()
    async with _client(app) as client:
        resp = await client.get("/storage/somejob")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_query_returns_results_when_storage_enabled():
    from crawl_tool.engine.contract import CrawlSummary

    summary = CrawlSummary(
        job_id="abc",
        seed_url="https://test.com",
        goal="news",
        generated_at="2026-06-25T00:00:00Z",
        total_pages=3,
        successful=3,
        failed=0,
    )
    with (
        patch("crawl_tool.engine.service.StorageSettings") as mock_settings_cls,
        patch("crawl_tool.engine.service.run_query", new_callable=AsyncMock) as mock_query,
    ):
        mock_settings_cls.from_env.return_value = MagicMock(enabled=True)
        mock_query.return_value = [summary]
        app = create_app()
        async with _client(app) as client:
            resp = await client.post("/query", json={"seed_url": "test.com"})
    assert resp.status_code == 200
    assert resp.json()[0]["job_id"] == "abc"


@pytest.mark.asyncio
async def test_storage_endpoint_returns_file_when_found():
    with (
        patch("crawl_tool.engine.service.StorageSettings") as mock_settings_cls,
        patch("crawl_tool.engine.service.get_result", new_callable=AsyncMock) as mock_get,
    ):
        mock_settings_cls.from_env.return_value = MagicMock(enabled=True)
        mock_get.return_value = b'{"meta": {}, "pages": []}'
        app = create_app()
        async with _client(app) as client:
            resp = await client.get("/storage/abc123")
    assert resp.status_code == 200
    assert b'"meta"' in resp.content


@pytest.mark.asyncio
async def test_storage_endpoint_returns_404_when_not_found():
    with (
        patch("crawl_tool.engine.service.StorageSettings") as mock_settings_cls,
        patch("crawl_tool.engine.service.get_result", new_callable=AsyncMock) as mock_get,
    ):
        mock_settings_cls.from_env.return_value = MagicMock(enabled=True)
        mock_get.return_value = None
        app = create_app()
        async with _client(app) as client:
            resp = await client.get("/storage/missing")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_job_uploads_to_storage_on_success():
    with (
        patch("crawl_tool.engine.service.execute", new_callable=AsyncMock) as mock_execute,
        patch("crawl_tool.engine.service.StorageSettings") as mock_settings_cls,
        patch("crawl_tool.engine.service.put_result", new_callable=AsyncMock) as mock_put,
    ):
        mock_execute.return_value = _PAYLOAD
        mock_settings_cls.from_env.return_value = MagicMock(enabled=True)
        app = create_app()
        async with _client(app) as client:
            resp = await client.post("/crawl", json={"seed_url": "https://example.com"})
            job_id = resp.json()["job_id"]
            await _poll_until_terminal(client, job_id)
    mock_put.assert_awaited_once()
    call_args = mock_put.call_args
    assert call_args.args[0] == job_id


@pytest.mark.asyncio
async def test_parse_endpoint_returns_parsed_fields():
    app = create_app()
    parsed = {"seed_url": "https://cafef.vn", "goal": "finance news"}
    with patch("crawl_tool.engine.service.parse_crawl_prompt", AsyncMock(return_value=parsed)):
        async with _client(app) as client:
            resp = await client.post("/parse", json={"prompt": "finance news from cafef.vn"})
    assert resp.status_code == 200
    assert resp.json()["seed_url"] == "https://cafef.vn"


@pytest.mark.asyncio
async def test_parse_endpoint_returns_422_on_parse_error():
    app = create_app()
    with patch(
        "crawl_tool.engine.service.parse_crawl_prompt",
        AsyncMock(side_effect=PromptParseError("no url found")),
    ):
        async with _client(app) as client:
            resp = await client.post("/parse", json={"prompt": "vague prompt"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_storage_returns_overview():
    objects = [{"job_id": "abc", "size_bytes": 512, "last_modified": "2026-06-29T10:00:00+00:00"}]
    with patch("crawl_tool.engine.service.list_results", AsyncMock(return_value=objects)):
        with patch.dict("os.environ", {"MINIO_ENDPOINT": "localhost:9000"}):
            app2 = create_app()
            async with _client(app2) as client:
                resp = await client.get("/storage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_files"] == 1
    assert body["total_size_bytes"] == 512


@pytest.mark.asyncio
async def test_get_storage_returns_503_when_not_configured():
    app = create_app()
    async with _client(app) as client:
        resp = await client.get("/storage")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_delete_storage_returns_204():
    with patch.dict("os.environ", {"MINIO_ENDPOINT": "localhost:9000"}):
        app = create_app()
    with patch("crawl_tool.engine.service.delete_stored_result", AsyncMock(return_value=None)):
        async with _client(app) as client:
            resp = await client.delete("/storage/abc123")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_storage_returns_503_when_not_configured():
    app = create_app()
    async with _client(app) as client:
        resp = await client.delete("/storage/abc123")
    assert resp.status_code == 503
