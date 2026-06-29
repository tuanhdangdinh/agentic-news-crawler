# Gradio Multi-Page UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the Gradio UI into three sidebar-navigated pages (Quick Crawl, Advanced Crawl, Storage) backed by new engine endpoints for prompt parsing and MinIO object management.

**Architecture:** The engine gains `POST /parse`, `GET /storage`, and `DELETE /storage/{job_id}`. The Gradio layer is split from one 955-line `ui.py` into focused modules: `ui_styles.py` (CSS/JS), `ui_shared.py` (shared helpers), `ui_advanced_crawl.py` (current form refactored), `ui_quick_crawl.py` (NL prompt → parse → edit → run), `ui_storage.py` (MinIO stats + DuckDB query). `app.py` composes all three behind a styled sidebar nav.

**Tech Stack:** FastAPI, Gradio 5.x, MinIO Python SDK, httpx, pytest-asyncio, pytest-httpx

## Global Constraints

- Python type hints on all public functions; use `X | Y` not `Optional[X]`
- All I/O is `async`; sync MinIO calls wrapped in `asyncio.to_thread`
- Run tests with `uv run python -m pytest` (not `uv run pytest`)
- Lint: `uv run ruff check .` must pass after every commit
- No comments unless the WHY is non-obvious
- Commit messages: subject line only, Conventional Commits format (`feat:`, `refactor:`, `test:`, etc.)
- Never import `crawl_tool.engine` modules from `crawl_tool.gradio` — UI talks to engine over HTTP only

---

## File Map

**Created:**
- `src/crawl_tool/gradio/ui_styles.py` — `CUSTOM_CSS`, `_RESULT_JS` constants
- `src/crawl_tool/gradio/ui_shared.py` — `_s`, `_validate_url`, `_parse_patterns`, `_parse_schema`, `_build_request`, `_output_path`, `run_crawl`, `_sample_tags`, all `_*_SAMPLES` constants
- `src/crawl_tool/gradio/ui_advanced_crawl.py` — `build_advanced_crawl_page()`, no History tab
- `src/crawl_tool/gradio/ui_quick_crawl.py` — `build_quick_crawl_page()`, two-phase NL flow
- `src/crawl_tool/gradio/ui_storage.py` — `build_storage_page()`, three panels
- `tests/gradio/test_ui_shared.py` — tests for helpers moved from `ui.py`
- `tests/gradio/test_ui_quick_crawl.py` — tests for quick crawl page helpers
- `tests/gradio/test_ui_storage.py` — tests for storage page helpers

**Modified:**
- `src/crawl_tool/engine/storage.py` — add `_list_results_sync`, `_delete_result_sync`, `list_results`, `delete_stored_result`
- `src/crawl_tool/engine/contract.py` — add `ParseRequest`, `StorageObject`, `StorageOverview`
- `src/crawl_tool/engine/service.py` — add `POST /parse`, `GET /storage`, `DELETE /storage/{job_id}`
- `src/crawl_tool/gradio/client.py` — add `parse_prompt`, `get_storage_overview`, `delete_stored_result`
- `src/crawl_tool/gradio/app.py` — full rewrite: sidebar nav + three page columns
- `src/crawl_tool/gradio/dev_ui.py` — update imports from `ui` → `ui_styles` + `app`
- `tests/engine/test_storage.py` — add tests for new storage functions
- `tests/engine/test_service.py` — add tests for three new endpoints
- `tests/gradio/test_client.py` — add tests for three new client functions
- `tests/gradio/test_ui.py` — update import from `ui` → `ui_shared`

**Deleted:**
- `src/crawl_tool/gradio/ui.py` — contents distributed across new modules

---

## Task 1: Storage module — list and delete functions

**Files:**
- Modify: `src/crawl_tool/engine/storage.py`
- Modify: `tests/engine/test_storage.py`

**Interfaces:**
- Produces:
  - `_list_results_sync(settings: StorageSettings) -> list[dict]` — each dict: `{job_id: str, size_bytes: int, last_modified: str}` (ISO format)
  - `_delete_result_sync(job_id: str, settings: StorageSettings) -> None`
  - `async list_results(settings: StorageSettings) -> list[dict]`
  - `async delete_stored_result(job_id: str, settings: StorageSettings) -> None`

- [ ] **Step 1: Write failing tests**

Add to `tests/engine/test_storage.py`:

```python
from datetime import datetime, timezone

def test_list_results_returns_objects():
    from crawl_tool.engine.storage import _list_results_sync

    mock_obj = MagicMock()
    mock_obj.object_name = "crawl-abc123.json"
    mock_obj.size = 1024
    mock_obj.last_modified = datetime(2026, 6, 29, 10, 0, 0, tzinfo=timezone.utc)

    mock_client = MagicMock()
    mock_client.list_objects.return_value = [mock_obj]

    with patch("crawl_tool.engine.storage._make_client", return_value=mock_client):
        results = _list_results_sync(_settings())

    assert results == [
        {"job_id": "abc123", "size_bytes": 1024, "last_modified": "2026-06-29T10:00:00+00:00"}
    ]
    mock_client.list_objects.assert_called_once_with("crawl-results")


def test_list_results_empty_bucket():
    from crawl_tool.engine.storage import _list_results_sync

    mock_client = MagicMock()
    mock_client.list_objects.return_value = []

    with patch("crawl_tool.engine.storage._make_client", return_value=mock_client):
        results = _list_results_sync(_settings())

    assert results == []


def test_delete_result_calls_remove_object():
    from crawl_tool.engine.storage import _delete_result_sync

    mock_client = MagicMock()

    with patch("crawl_tool.engine.storage._make_client", return_value=mock_client):
        _delete_result_sync("abc123", _settings())

    mock_client.remove_object.assert_called_once_with("crawl-results", "crawl-abc123.json")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/engine/test_storage.py -k "list_results or delete_result" -v
```

Expected: `FAILED` — `cannot import name '_list_results_sync'`

- [ ] **Step 3: Implement functions in `storage.py`**

Add after `_get_result_sync`:

```python
def _list_results_sync(settings: StorageSettings) -> list[dict]:
    client = _make_client(settings)
    results = []
    for obj in client.list_objects(settings.bucket):
        name: str = obj.object_name
        if not name.startswith("crawl-") or not name.endswith(".json"):
            continue
        job_id = name[len("crawl-"):-len(".json")]
        results.append({
            "job_id": job_id,
            "size_bytes": obj.size,
            "last_modified": obj.last_modified.isoformat(),
        })
    return results


def _delete_result_sync(job_id: str, settings: StorageSettings) -> None:
    client = _make_client(settings)
    client.remove_object(settings.bucket, f"crawl-{job_id}.json")
```

Add async wrappers after the existing `get_result`:

```python
async def list_results(settings: StorageSettings) -> list[dict]:
    """List all stored crawl results. Returns [{job_id, size_bytes, last_modified}]."""
    return await asyncio.to_thread(_list_results_sync, settings)


async def delete_stored_result(job_id: str, settings: StorageSettings) -> None:
    """Delete crawl-{job_id}.json from MinIO."""
    await asyncio.to_thread(_delete_result_sync, job_id, settings)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run python -m pytest tests/engine/test_storage.py -v
```

Expected: all storage tests pass.

- [ ] **Step 5: Lint**

```bash
uv run ruff check src/crawl_tool/engine/storage.py
```

- [ ] **Step 6: Commit**

```bash
git add src/crawl_tool/engine/storage.py tests/engine/test_storage.py
git commit -m "feat: add list_results and delete_stored_result to storage module"
```

---

## Task 2: Contract models for parse and storage overview

**Files:**
- Modify: `src/crawl_tool/engine/contract.py`
- Modify: `tests/engine/test_contract.py`

**Interfaces:**
- Produces:
  - `ParseRequest` — `prompt: str`
  - `StorageObject` — `job_id: str`, `size_bytes: int`, `last_modified: str`
  - `StorageOverview` — `total_files: int`, `total_size_bytes: int`, `last_modified: str | None`, `objects: list[StorageObject]`

- [ ] **Step 1: Write failing tests**

Open `tests/engine/test_contract.py` and add:

```python
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
    ov = StorageOverview(total_files=0, total_size_bytes=0, last_modified=None, objects=[])
    assert ov.total_files == 0
    assert ov.objects == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/engine/test_contract.py -k "parse_request or storage_overview" -v
```

Expected: `FAILED` — `cannot import name 'ParseRequest'`

- [ ] **Step 3: Add models to `contract.py`**

Append at the end of `contract.py`:

```python
class ParseRequest(BaseModel):
    """Body for POST /parse."""

    prompt: str


class StorageObject(BaseModel):
    """One object in the MinIO bucket."""

    job_id: str
    size_bytes: int
    last_modified: str


class StorageOverview(BaseModel):
    """Response for GET /storage."""

    total_files: int
    total_size_bytes: int
    last_modified: str | None
    objects: list[StorageObject]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run python -m pytest tests/engine/test_contract.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/crawl_tool/engine/contract.py tests/engine/test_contract.py
git commit -m "feat: add ParseRequest, StorageObject, StorageOverview contract models"
```

---

## Task 3: Engine service — three new endpoints

**Files:**
- Modify: `src/crawl_tool/engine/service.py`
- Modify: `tests/engine/test_service.py`

**Interfaces:**
- Consumes: `ParseRequest`, `StorageOverview`, `StorageObject` from Task 2; `list_results`, `delete_stored_result` from Task 1
- Produces:
  - `POST /parse` → `200: dict` | `422: {detail}`
  - `GET /storage` → `200: StorageOverview` | `503`
  - `DELETE /storage/{job_id}` → `204` | `404` | `503`

- [ ] **Step 1: Write failing tests**

Add to `tests/engine/test_service.py`:

```python
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
    app = create_app()
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/engine/test_service.py -k "parse_endpoint or get_storage or delete_storage" -v
```

Expected: `FAILED` — endpoints not found (404)

- [ ] **Step 3: Add imports to `service.py`**

Add to the import block at the top of `service.py`:

```python
from crawl_tool.engine.contract import (
    ...  # existing imports
    ParseRequest,
    StorageObject,
    StorageOverview,
)
from crawl_tool.engine.storage import (
    StorageSettings,
    delete_stored_result,
    get_result,
    list_results,
    put_result,
)
```

Also add `S3Error` import:
```python
from minio.error import S3Error
```

- [ ] **Step 4: Add three endpoints inside `create_app()`**

Add after the existing `@app.get("/storage/{job_id}")` endpoint:

```python
    @app.post("/parse", status_code=200)
    async def parse_prompt(request: ParseRequest) -> dict:
        """Parse a natural-language crawl description into structured fields."""
        try:
            return await parse_crawl_prompt(request.prompt)
        except PromptParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/storage")
    async def get_storage_overview() -> StorageOverview:
        """List all stored crawl results with bucket-level stats."""
        if not storage_settings.enabled:
            raise HTTPException(status_code=503, detail="storage not configured")
        objects = await list_results(storage_settings)
        last_mod = max((o["last_modified"] for o in objects), default=None)
        return StorageOverview(
            total_files=len(objects),
            total_size_bytes=sum(o["size_bytes"] for o in objects),
            last_modified=last_mod,
            objects=[StorageObject(**o) for o in objects],
        )

    @app.delete("/storage/{job_id}", status_code=204)
    async def delete_storage_result(job_id: str) -> Response:
        """Delete a stored crawl result from MinIO."""
        if not storage_settings.enabled:
            raise HTTPException(status_code=503, detail="storage not configured")
        try:
            await delete_stored_result(job_id, storage_settings)
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                raise HTTPException(status_code=404, detail="result not found") from exc
            raise
        return Response(status_code=204)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run python -m pytest tests/engine/test_service.py -v
```

Expected: all service tests pass.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/crawl_tool/engine/service.py
git add src/crawl_tool/engine/service.py tests/engine/test_service.py
git commit -m "feat: add POST /parse, GET /storage, DELETE /storage/{job_id} endpoints"
```

---

## Task 4: Gradio client — three new functions

**Files:**
- Modify: `src/crawl_tool/gradio/client.py`
- Modify: `tests/gradio/test_client.py`

**Interfaces:**
- Produces:
  - `async parse_prompt(prompt: str, *, base_url: str = ENGINE_URL) -> dict` — returns parsed fields dict; raises `httpx.HTTPStatusError` on 422
  - `async get_storage_overview(*, base_url: str = ENGINE_URL) -> dict` — returns StorageOverview dict
  - `async delete_stored_result(job_id: str, *, base_url: str = ENGINE_URL) -> None`

- [ ] **Step 1: Write failing tests**

Add to `tests/gradio/test_client.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/gradio/test_client.py -k "parse_prompt or storage_overview or delete_stored" -v
```

Expected: `FAILED` — function not defined

- [ ] **Step 3: Add functions to `client.py`**

Append to `src/crawl_tool/gradio/client.py`:

```python
async def parse_prompt(
    prompt: str,
    *,
    base_url: str = ENGINE_URL,
) -> dict:
    """Parse a natural-language crawl description into structured fields via POST /parse."""
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        response = await http.post("/parse", json={"prompt": prompt})
        response.raise_for_status()
        return response.json()


async def get_storage_overview(
    *,
    base_url: str = ENGINE_URL,
) -> dict:
    """Fetch bucket stats and object list from GET /storage."""
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        response = await http.get("/storage")
        response.raise_for_status()
        return response.json()


async def delete_stored_result(
    job_id: str,
    *,
    base_url: str = ENGINE_URL,
) -> None:
    """Delete a stored crawl result via DELETE /storage/{job_id}."""
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        response = await http.delete(f"/storage/{job_id}")
        response.raise_for_status()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run python -m pytest tests/gradio/test_client.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/crawl_tool/gradio/client.py tests/gradio/test_client.py
git commit -m "feat: add parse_prompt, get_storage_overview, delete_stored_result to Gradio client"
```

---

## Task 5: Extract styles and shared helpers

**Files:**
- Create: `src/crawl_tool/gradio/ui_styles.py`
- Create: `src/crawl_tool/gradio/ui_shared.py`
- Create: `tests/gradio/test_ui_shared.py`
- Modify: `tests/gradio/test_ui.py` — update import from `ui` → `ui_shared`

**Interfaces:**
- Produces from `ui_styles.py`: `CUSTOM_CSS: str`, `_RESULT_JS: str`
- Produces from `ui_shared.py`:
  - `_s(value: str | None) -> str`
  - `_validate_url(value: str | None) -> str`
  - `_parse_patterns(value: str | None) -> list[str]`
  - `_parse_schema(value: str | None) -> dict | None`
  - `_build_request(seed_url, goal, extract_prompt, extract_schema, max_depth, max_pages, token_budget, same_domain, include_patterns, exclude_patterns, date_filter, include_undated, css_selector, max_chars) -> dict`
  - `_output_path(fmt: str) -> str`
  - `async run_crawl(...) -> AsyncIterator[tuple]`
  - `_sample_tags(samples: list[tuple[str, str]], target: gr.Textbox) -> None`
  - `_SEED_URL_SAMPLES`, `_GOAL_SAMPLES`, `_EXTRACT_PROMPT_SAMPLES`, `_DATE_FILTER_SAMPLES`, `_CSS_SELECTOR_SAMPLES`

- [ ] **Step 1: Write failing tests**

Create `tests/gradio/test_ui_shared.py`:

```python
"""Tests for ui_shared helpers."""
from __future__ import annotations

import pytest


def test_s_strips_and_returns_empty_for_none():
    from crawl_tool.gradio.ui_shared import _s
    assert _s(None) == ""
    assert _s("  hello  ") == "hello"


def test_parse_patterns_removes_blank_lines():
    from crawl_tool.gradio.ui_shared import _parse_patterns
    assert _parse_patterns("  *article*\n\n *video*  ") == ["*article*", "*video*"]
    assert _parse_patterns(None) == []


def test_build_request_assembles_dict():
    from crawl_tool.gradio.ui_shared import _build_request
    request = _build_request(
        "https://cafef.vn", " collect news ", " extract title ",
        '{"type": "object", "properties": {}}',
        2, 5, 1000, False, "*article*\n*news*", "*video*",
        " last 7 days ", False, " article ", 8000,
    )
    assert request["seed_url"] == "https://cafef.vn"
    assert request["goal"] == "collect news"
    assert request["max_depth"] == 2
    assert request["extract_schema"] == {"type": "object", "properties": {}}
    assert request["include_patterns"] == ["*article*", "*news*"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/gradio/test_ui_shared.py -v
```

Expected: `FAILED` — module not found

- [ ] **Step 3: Create `ui_styles.py`**

Create `src/crawl_tool/gradio/ui_styles.py` by moving the `CUSTOM_CSS` and `_RESULT_JS` constants verbatim from `ui.py` (lines 29–460):

```python
"""Shared CSS and JavaScript for the Gradio interface."""

from __future__ import annotations

_RESULT_JS = """
() => {
  window.rtSelect = function(row, id) {
  ...  # paste exact content from ui.py lines 29-95
  };
}
"""

CUSTOM_CSS = """
:root {
  ...  # paste exact content from ui.py lines 97-460
}
"""
```

(Copy the exact strings from `ui.py` — do not paraphrase.)

- [ ] **Step 4: Create `ui_shared.py`**

Create `src/crawl_tool/gradio/ui_shared.py` with the helpers and constants moved from `ui.py`:

```python
"""Shared helpers and sample data for all crawl UI pages."""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import gradio as gr
import httpx

from crawl_tool.gradio.client import (
    download_result,
    poll_until_done,
    start_crawl,
)
from crawl_tool.gradio.ui_results import build_result_table, render_result_table_html

_SEED_URL_SAMPLES = [
    ("CafeF", "https://cafef.vn"),
    ("VnEconomy", "https://vneconomy.vn"),
    ("Vietstock", "https://vietstock.vn"),
    ("VnExpress", "https://vnexpress.net/kinh-doanh"),
    ("Tuoi Tre", "https://tuoitre.vn/kinh-doanh"),
]

_GOAL_SAMPLES = [
    ("Recent banking", "Collect the 20 most recent banking articles"),
    ("Stock market", "Find all recent stock market news"),
    ("Earnings reports", "Get the top earnings-report articles"),
    ("USD/VND", "Gather articles about USD/VND exchange rate"),
]

_EXTRACT_PROMPT_SAMPLES = [
    ("Article basics", "Extract title, publish date, author, and one-sentence summary"),
    ("Financial facts", "Extract title, publish date, stock tickers, and key financial figures"),
    ("Dates only", "Extract article title, URL, and publish date only"),
]

_DATE_FILTER_SAMPLES = [
    ("7 days", "last 7 days"),
    ("30 days", "last 30 days"),
    ("Since date", "since 2024-01-01"),
    ("Date range", "between 2024-01-01 and 2024-12-31"),
]

_CSS_SELECTOR_SAMPLES = [
    ("Main article", "article.main-content"),
    ("Detail content", ".detail-content"),
    ("Article body ID", "#article-body"),
    ("Article body class", ".article__body"),
]


def _s(value: str | None) -> str:
    return (value or "").strip()


def _parse_patterns(value: str | None) -> list[str]:
    if not value:
        return []
    return [line.strip() for line in value.splitlines() if line.strip()]


def _parse_schema(value: str | None) -> dict | None:
    if not value or not value.strip():
        return None
    try:
        schema = json.loads(value)
    except json.JSONDecodeError as exc:
        raise gr.Error(f"Invalid JSON Schema: {exc.msg} at line {exc.lineno}") from exc
    if not isinstance(schema, dict):
        raise gr.Error("JSON Schema must be a JSON object.")
    return schema


def _validate_url(value: str | None) -> str:
    url = _s(value)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise gr.Error("Seed URL must be a complete HTTP or HTTPS URL.")
    return url


def _build_request(
    seed_url: str,
    goal: str | None,
    extract_prompt: str | None,
    extract_schema: str | None,
    max_depth: float,
    max_pages: float,
    token_budget: float,
    same_domain: bool,
    include_patterns: str | None,
    exclude_patterns: str | None,
    date_filter: str | None,
    include_undated: bool,
    css_selector: str | None,
    max_chars: float,
) -> dict:
    return {
        "seed_url": seed_url,
        "goal": _s(goal),
        "extract_prompt": _s(extract_prompt),
        "extract_schema": _parse_schema(extract_schema),
        "max_depth": int(max_depth),
        "max_pages": int(max_pages),
        "token_budget": int(token_budget),
        "same_domain": same_domain,
        "include_patterns": _parse_patterns(include_patterns),
        "exclude_patterns": _parse_patterns(exclude_patterns),
        "date_filter": _s(date_filter),
        "include_undated": include_undated,
        "css_selector": _s(css_selector),
        "max_chars": int(max_chars),
    }


def _output_path(fmt: str) -> str:
    suffix = ".jsonl" if fmt == "jsonl" else ".json"
    return str(Path(tempfile.gettempdir()) / f"crawl-tool-{uuid4().hex}{suffix}")


async def run_crawl(
    seed_url: str | None,
    goal: str | None,
    extract_prompt: str | None,
    extract_schema: str | None,
    max_depth: float,
    max_pages: float,
    token_budget: float,
    same_domain: bool,
    include_patterns: str | None,
    exclude_patterns: str | None,
    date_filter: str | None,
    include_undated: bool,
    css_selector: str | None,
    max_chars: float,
    output_format: str,
) -> AsyncIterator[tuple]:
    """Drive a crawl over HTTP and yield progress and result components."""
    url = _validate_url(seed_url)
    request = _build_request(
        url, goal, extract_prompt, extract_schema, max_depth, max_pages,
        token_budget, same_domain, include_patterns, exclude_patterns,
        date_filter, include_undated, css_selector, max_chars,
    )
    extraction_requested = bool(_s(extract_prompt) or _s(extract_schema))
    hold = (gr.update(), gr.update(), gr.update(), gr.update(), gr.update())

    try:
        job_id = await start_crawl(request)
        status: dict = {}
        async for status in poll_until_done(job_id):
            if status["status"] == "running":
                collected = status.get("progress", {}).get("pages_collected", 0)
                yield (f"Running - {collected} page(s) collected...", *hold)
    except httpx.HTTPError as exc:
        yield (f"Engine error: {exc}", *hold)
        return

    if status.get("status") == "error":
        yield (f"Crawl failed: {status.get('error')}", *hold)
        return

    payload = status["payload"]
    table = build_result_table(payload, "Extracted", extraction_requested=extraction_requested)
    table_html = render_result_table_html(table)
    meta = payload["meta"]
    status_message = (
        f"Collected {meta['total_pages']} page(s), "
        f"{meta['successful']} successful, {meta['failed']} failed."
    )

    fmt = output_format.lower()
    try:
        data = await download_result(job_id, fmt)
    except httpx.HTTPError as exc:
        yield (f"Engine error: {exc}", *hold)
        return
    output_path = _output_path(fmt)
    await asyncio.to_thread(Path(output_path).write_bytes, data)

    yield (status_message, table_html, payload, payload, extraction_requested, output_path)


def _sample_tags(samples: list[tuple[str, str]], target: gr.Textbox) -> None:
    """Render compact preset buttons that fill a textbox client-side."""
    with gr.Row(elem_classes="sample-strip"):
        for label, value in samples:
            btn = gr.Button(label, size="sm", min_width=0, elem_classes="sample-tag")
            btn.click(None, outputs=target, js=f"() => {json.dumps(value)}")
```

- [ ] **Step 5: Update `tests/gradio/test_ui.py`**

Change the import at the top of `tests/gradio/test_ui.py`:

```python
# Before:
from crawl_tool.gradio import ui

# After:
from crawl_tool.gradio import ui_shared as ui
```

This keeps all existing assertions working since the functions have the same names.

- [ ] **Step 6: Run all Gradio tests**

```bash
uv run python -m pytest tests/gradio/ -v
```

Expected: all pass (the `test_ui.py` tests now exercise `ui_shared`).

- [ ] **Step 7: Commit**

```bash
git add src/crawl_tool/gradio/ui_styles.py src/crawl_tool/gradio/ui_shared.py \
        tests/gradio/test_ui.py tests/gradio/test_ui_shared.py
git commit -m "refactor: extract CUSTOM_CSS, _RESULT_JS, and shared crawl helpers from ui.py"
```

---

## Task 6: Advanced crawl page

**Files:**
- Create: `src/crawl_tool/gradio/ui_advanced_crawl.py`

**Interfaces:**
- Consumes: all helpers from `ui_shared.py`
- Produces: `build_advanced_crawl_page() -> gr.Column`

- [ ] **Step 1: Create `ui_advanced_crawl.py`**

This is a refactor of the form and results section of `ui.py`. The function returns a `gr.Column` that `app.py` will show/hide. The History tab is removed from results.

```python
"""Advanced crawl page — full form with all controls."""

from __future__ import annotations

import gradio as gr

from crawl_tool.gradio.ui_results import build_result_table, render_result_table_html
from crawl_tool.gradio.ui_shared import (
    _CSS_SELECTOR_SAMPLES,
    _DATE_FILTER_SAMPLES,
    _EXTRACT_PROMPT_SAMPLES,
    _GOAL_SAMPLES,
    _SEED_URL_SAMPLES,
    _sample_tags,
    run_crawl,
)


def build_advanced_crawl_page() -> gr.Column:
    """Build the advanced crawl form as a hideable column."""
    _init_table_html = render_result_table_html(
        build_result_table({}, "Extracted", extraction_requested=False)
    )

    with gr.Column(visible=False) as col:
        seed_url = gr.Textbox(
            label="Seed URL",
            placeholder="https://cafef.vn/ngan-hang.chn",
            info="Starting URL the agent crawls from. Must be a full HTTP or HTTPS address.",
        )
        _sample_tags(_SEED_URL_SAMPLES, seed_url)

        with gr.Row(equal_height=False):
            with gr.Column(scale=1, min_width=360, elem_classes="primary-panel"):
                gr.HTML('<p class="primary-panel-title">What to crawl</p>')
                goal = gr.Textbox(
                    label="Crawl goal",
                    placeholder="Collect the 20 most recent banking and stock market articles",
                    info="Natural-language objective.",
                    lines=3,
                )
                _sample_tags(_GOAL_SAMPLES, goal)
                with gr.Row(equal_height=True):
                    date_filter = gr.Textbox(
                        label="Date filter",
                        placeholder="last 7 days",
                        info="Enforced publication-date range.",
                        scale=3,
                        min_width=240,
                    )
                    include_undated = gr.Checkbox(
                        value=True,
                        label="Include undated",
                        info="Keep pages whose publish date cannot be detected.",
                        scale=1,
                        min_width=130,
                    )
                _sample_tags(_DATE_FILTER_SAMPLES, date_filter)

            with gr.Column(scale=1, min_width=360, elem_classes="primary-panel"):
                gr.HTML('<p class="primary-panel-title">What to return</p>')
                extract_prompt = gr.Textbox(
                    label="Extraction prompt",
                    placeholder="Extract the article title, publish date, author name, and key financial figures",
                    info="Fields to pull from each article. Leave blank to skip structured extraction.",
                    lines=3,
                )
                _sample_tags(_EXTRACT_PROMPT_SAMPLES, extract_prompt)
                with gr.Row(equal_height=True):
                    max_pages = gr.Slider(1, 100, value=4, step=1, label="Maximum pages", scale=2, min_width=180)
                    max_depth = gr.Slider(0, 5, value=1, step=1, label="Maximum depth", scale=2, min_width=180)
                output_format = gr.Radio(["JSON", "JSONL"], value="JSON", label="Download format")

        with gr.Accordion("Extraction schema", open=False):
            extract_schema = gr.Code(label="Optional JSON Schema", language="json", lines=10)
            gr.Markdown("_Paste a JSON Schema to enforce exact output shape._")

        with gr.Accordion("Crawl controls", open=False):
            with gr.Row():
                same_domain = gr.Checkbox(value=True, label="Stay on seed domain")
                css_selector = gr.Textbox(
                    label="CSS selector",
                    placeholder="article.main-content",
                    info="Scope page content to this element.",
                )
            _sample_tags(_CSS_SELECTOR_SAMPLES, css_selector)
            with gr.Row():
                max_chars = gr.Number(value=0, precision=0, label="Max markdown chars")
                token_budget = gr.Number(value=500_000, precision=0, label="Token budget")
            with gr.Row():
                include_patterns = gr.Textbox(label="Include URL patterns", lines=4)
                exclude_patterns = gr.Textbox(label="Exclude URL patterns", lines=4)

        run_button = gr.Button("Run crawl", variant="primary", elem_classes="run-button")
        status = gr.Markdown("")
        download = gr.File(label="Download result", visible=False)
        payload_state = gr.State({})
        extraction_state = gr.State(False)

        with gr.Tabs():
            with gr.TabItem("Extracted Data"):
                with gr.Row():
                    mode_radio = gr.Radio(["Extracted", "All pages"], value="Extracted", label="Show", scale=0)
                table_html = gr.HTML(value=_init_table_html)
            with gr.TabItem("Raw JSON"):
                json_preview = gr.JSON(label="Raw payload", value=None, open=True)

        inputs = [
            seed_url, goal, extract_prompt, extract_schema, max_depth, max_pages,
            token_budget, same_domain, include_patterns, exclude_patterns,
            date_filter, include_undated, css_selector, max_chars, output_format,
        ]
        run_button.click(
            fn=run_crawl,
            inputs=inputs,
            outputs=[status, table_html, payload_state, json_preview, extraction_state, download],
            concurrency_limit=1,
        )

        def on_mode_change(mode: str, payload: dict, extraction_requested: bool) -> str:
            table = build_result_table(payload, mode, extraction_requested=extraction_requested)
            return render_result_table_html(table)

        mode_radio.change(
            fn=on_mode_change,
            inputs=[mode_radio, payload_state, extraction_state],
            outputs=[table_html],
        )

    return col
```

- [ ] **Step 2: Smoke-test the module imports cleanly**

```bash
uv run python -c "from crawl_tool.gradio.ui_advanced_crawl import build_advanced_crawl_page; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/crawl_tool/gradio/ui_advanced_crawl.py
git commit -m "feat: add ui_advanced_crawl page (refactored from ui.py, no History tab)"
```

---

## Task 7: Quick crawl page

**Files:**
- Create: `src/crawl_tool/gradio/ui_quick_crawl.py`
- Create: `tests/gradio/test_ui_quick_crawl.py`

**Interfaces:**
- Consumes: `parse_prompt` from `client.py`; `run_crawl` from `ui_shared.py`
- Produces: `build_quick_crawl_page() -> gr.Column`
- Internal helpers (testable in isolation):
  - `_populate_fields(parsed: dict) -> tuple` — returns gr.update values for all Phase 2 inputs
  - `_inferred_chip_html(parsed: dict) -> str` — renders chip strip showing inferred vs. default fields

- [ ] **Step 1: Write failing tests**

Create `tests/gradio/test_ui_quick_crawl.py`:

```python
"""Tests for quick crawl page helpers."""
from __future__ import annotations


def test_populate_fields_fills_parsed_values():
    from crawl_tool.gradio.ui_quick_crawl import _populate_fields
    parsed = {
        "seed_url": "https://cafef.vn",
        "goal": "finance news",
        "date_filter": "last 7 days",
        "extract_prompt": "extract title",
        "max_depth": 2,
        "max_pages": 15,
    }
    updates = _populate_fields(parsed)
    # returns a tuple of 6 gr.update dicts in order:
    # seed_url, goal, date_filter, extract_prompt, max_depth, max_pages
    assert len(updates) == 6
    assert updates[0]["value"] == "https://cafef.vn"
    assert updates[1]["value"] == "finance news"
    assert updates[2]["value"] == "last 7 days"
    assert updates[3]["value"] == "extract title"
    assert updates[4]["value"] == 2
    assert updates[5]["value"] == 15


def test_populate_fields_uses_defaults_for_missing_keys():
    from crawl_tool.gradio.ui_quick_crawl import _populate_fields
    parsed = {"seed_url": "https://cafef.vn"}
    updates = _populate_fields(parsed)
    assert updates[1]["value"] == ""       # goal default
    assert updates[4]["value"] == 1        # max_depth default
    assert updates[5]["value"] == 10       # max_pages default


def test_inferred_chip_html_marks_found_fields():
    from crawl_tool.gradio.ui_quick_crawl import _inferred_chip_html
    html = _inferred_chip_html({"seed_url": "https://cafef.vn", "goal": "news"})
    assert "seed_url" in html
    assert "goal" in html
    assert "✓" in html


def test_inferred_chip_html_marks_default_fields():
    from crawl_tool.gradio.ui_quick_crawl import _inferred_chip_html
    html = _inferred_chip_html({"seed_url": "https://cafef.vn"})
    assert "date_filter" in html
    assert "default" in html.lower() or "—" in html
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/gradio/test_ui_quick_crawl.py -v
```

Expected: `FAILED` — module not found

- [ ] **Step 3: Create `ui_quick_crawl.py`**

```python
"""Quick crawl page — one-prompt NL flow with parse-then-edit."""

from __future__ import annotations

import gradio as gr
import httpx

from crawl_tool.gradio.client import parse_prompt
from crawl_tool.gradio.ui_results import build_result_table, render_result_table_html
from crawl_tool.gradio.ui_shared import (
    _EXTRACT_PROMPT_SAMPLES,
    _sample_tags,
    run_crawl,
)

_PROMPT_SAMPLES = [
    ("Finance CafeF 7d", "Get finance and banking news from https://cafef.vn for the last 7 days, extract title, author, and one-sentence summary"),
    ("Stock VnEconomy", "Collect the 20 most recent stock market articles from https://vneconomy.vn, extract title, publish date, and tickers mentioned"),
    ("USD/VND VietnamPlus", "Find articles about USD/VND exchange rate on https://en.vietnamplus.vn from the last 30 days"),
]

_INFERRED_FIELDS = ["seed_url", "goal", "date_filter", "extract_prompt", "max_depth", "max_pages"]
_FIELD_DEFAULTS: dict[str, object] = {
    "seed_url": "", "goal": "", "date_filter": "",
    "extract_prompt": "", "max_depth": 1, "max_pages": 10,
}


def _populate_fields(parsed: dict) -> tuple:
    """Return gr.update values for all Phase 2 inputs from the parsed dict."""
    return tuple(
        gr.update(value=parsed.get(field, _FIELD_DEFAULTS[field]))
        for field in _INFERRED_FIELDS
    )


def _inferred_chip_html(parsed: dict) -> str:
    chips = []
    for field in _INFERRED_FIELDS:
        if field in parsed:
            chips.append(f'<span class="chip">{field} ✓</span>')
        else:
            chips.append(f'<span class="chip" style="opacity:0.4">{field} — default</span>')
    return f'<div class="chip-list">{"".join(chips)}</div>'


def build_quick_crawl_page() -> gr.Column:
    """Build the quick crawl page as a hideable column."""
    _init_table_html = render_result_table_html(
        build_result_table({}, "Extracted", extraction_requested=False)
    )

    with gr.Column(visible=True) as col:
        # ── Phase 1: prompt input ────────────────────────────────────────
        with gr.Column(visible=True) as phase1_col:
            gr.Markdown("### Describe your crawl")
            gr.Markdown(
                "Include the site URL, what you want to collect, any date range, "
                "and what fields to extract."
            )
            prompt_input = gr.Textbox(
                label="Crawl prompt",
                placeholder=(
                    "Get finance and banking news from https://cafef.vn "
                    "for the last 7 days, extract title, author, and one-sentence summary"
                ),
                lines=5,
            )
            _sample_tags(_PROMPT_SAMPLES, prompt_input)
            parse_error = gr.Markdown("", visible=False)
            parse_btn = gr.Button("Parse →", variant="primary", elem_classes="run-button")

        # ── Phase 2: editable preview + run ─────────────────────────────
        with gr.Column(visible=False) as phase2_col:
            edit_link = gr.Button("← Edit prompt", size="sm")
            inferred_chips = gr.HTML("")

            seed_url_field = gr.Textbox(label="Seed URL")
            goal_field = gr.Textbox(label="Crawl goal", lines=2)
            date_filter_field = gr.Textbox(label="Date filter", placeholder="last 7 days")
            extract_prompt_field = gr.Textbox(label="Extraction prompt", lines=2)
            _sample_tags(_EXTRACT_PROMPT_SAMPLES, extract_prompt_field)
            with gr.Row():
                max_depth_field = gr.Slider(0, 5, value=1, step=1, label="Max depth", scale=1)
                max_pages_field = gr.Slider(1, 100, value=10, step=1, label="Max pages", scale=1)

            run_btn = gr.Button("Run crawl", variant="primary", elem_classes="run-button")

        # ── Results ──────────────────────────────────────────────────────
        run_status = gr.Markdown("")
        run_download = gr.File(label="Download result", visible=False)
        payload_state = gr.State({})
        extraction_state = gr.State(False)

        with gr.Tabs():
            with gr.TabItem("Extracted Data"):
                table_html = gr.HTML(value=_init_table_html)
            with gr.TabItem("Raw JSON"):
                json_preview = gr.JSON(label="Raw payload", value=None, open=True)

        # ── Event handlers ───────────────────────────────────────────────
        async def _on_parse(prompt: str):
            if not prompt.strip():
                yield (
                    gr.update(visible=True),   # phase1
                    gr.update(visible=False),  # phase2
                    gr.update(value="Enter a prompt first.", visible=True),  # error
                    *(_populate_fields({})),
                    gr.update(value=""),  # chips
                )
                return
            try:
                parsed = await parse_prompt(prompt)
            except httpx.HTTPStatusError as exc:
                msg = exc.response.json().get("detail", str(exc))
                yield (
                    gr.update(visible=True),
                    gr.update(visible=False),
                    gr.update(value=f"**Parse error:** {msg}", visible=True),
                    *(_populate_fields({})),
                    gr.update(value=""),
                )
                return
            except httpx.RequestError as exc:
                yield (
                    gr.update(visible=True),
                    gr.update(visible=False),
                    gr.update(value=f"**Engine unreachable:** {exc}", visible=True),
                    *(_populate_fields({})),
                    gr.update(value=""),
                )
                return
            yield (
                gr.update(visible=False),   # hide phase1
                gr.update(visible=True),    # show phase2
                gr.update(value="", visible=False),  # clear error
                *(_populate_fields(parsed)),
                gr.update(value=_inferred_chip_html(parsed)),
            )

        parse_btn.click(
            fn=_on_parse,
            inputs=[prompt_input],
            outputs=[
                phase1_col, phase2_col, parse_error,
                seed_url_field, goal_field, date_filter_field,
                extract_prompt_field, max_depth_field, max_pages_field,
                inferred_chips,
            ],
        )

        def _on_edit():
            return gr.update(visible=True), gr.update(visible=False)

        edit_link.click(fn=_on_edit, outputs=[phase1_col, phase2_col])

        async def _run_quick(seed_url, goal, extract_prompt, date_filter, max_depth, max_pages):
            async for frame in run_crawl(
                seed_url, goal, extract_prompt, None,
                max_depth, max_pages, 500_000, True,
                None, None, date_filter, True, None, 0, "JSON",
            ):
                yield frame

        run_btn.click(
            fn=_run_quick,
            inputs=[seed_url_field, goal_field, extract_prompt_field,
                    date_filter_field, max_depth_field, max_pages_field],
            outputs=[run_status, table_html, payload_state, json_preview, extraction_state, run_download],
            concurrency_limit=1,
        )

    return col
```

- [ ] **Step 4: Run tests**

```bash
uv run python -m pytest tests/gradio/test_ui_quick_crawl.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Smoke-test import**

```bash
uv run python -c "from crawl_tool.gradio.ui_quick_crawl import build_quick_crawl_page; print('ok')"
```

- [ ] **Step 6: Commit**

```bash
git add src/crawl_tool/gradio/ui_quick_crawl.py tests/gradio/test_ui_quick_crawl.py
git commit -m "feat: add quick crawl page with NL prompt parse-then-edit flow"
```

---

## Task 8: Storage page

**Files:**
- Create: `src/crawl_tool/gradio/ui_storage.py`
- Create: `tests/gradio/test_ui_storage.py`

**Interfaces:**
- Consumes: `get_storage_overview`, `delete_stored_result`, `download_from_storage`, `query_history` from `client.py`
- Produces: `build_storage_page() -> gr.Column`
- Internal helpers (testable):
  - `_format_size(size_bytes: int) -> str` — `1024 → "1.0 KB"`, `1048576 → "1.0 MB"`, `< 1024 → "512 B"`
  - `_build_stats_html(overview: dict) -> str` — renders stat chips HTML

- [ ] **Step 1: Write failing tests**

Create `tests/gradio/test_ui_storage.py`:

```python
"""Tests for storage page helpers."""
from __future__ import annotations


def test_format_size_bytes():
    from crawl_tool.gradio.ui_storage import _format_size
    assert _format_size(512) == "512 B"
    assert _format_size(1024) == "1.0 KB"
    assert _format_size(1536) == "1.5 KB"
    assert _format_size(1_048_576) == "1.0 MB"
    assert _format_size(1_073_741_824) == "1.0 GB"


def test_build_stats_html_shows_file_count():
    from crawl_tool.gradio.ui_storage import _build_stats_html
    overview = {
        "total_files": 5,
        "total_size_bytes": 10240,
        "last_modified": "2026-06-29T10:00:00+00:00",
        "objects": [],
    }
    html = _build_stats_html(overview)
    assert "5" in html
    assert "KB" in html
    assert "2026-06-29" in html


def test_build_stats_html_empty_bucket():
    from crawl_tool.gradio.ui_storage import _build_stats_html
    overview = {"total_files": 0, "total_size_bytes": 0, "last_modified": None, "objects": []}
    html = _build_stats_html(overview)
    assert "0" in html
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/gradio/test_ui_storage.py -v
```

Expected: `FAILED` — module not found

- [ ] **Step 3: Create `ui_storage.py`**

```python
"""Storage page — MinIO stats, object list, delete, and DuckDB query."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from uuid import uuid4

import gradio as gr
import httpx

from crawl_tool.gradio.client import (
    delete_stored_result,
    download_from_storage,
    get_storage_overview,
    query_history,
)


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1_073_741_824:
        return f"{size_bytes / 1_073_741_824:.1f} GB"
    if size_bytes >= 1_048_576:
        return f"{size_bytes / 1_048_576:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def _build_stats_html(overview: dict) -> str:
    total_files = overview.get("total_files", 0)
    total_size = _format_size(overview.get("total_size_bytes", 0))
    last_mod = overview.get("last_modified") or "—"
    if last_mod != "—":
        last_mod = last_mod[:10]  # date portion only
    return (
        '<div class="chip-list">'
        f'<span class="chip">Files: {total_files}</span>'
        f'<span class="chip">Size: {total_size}</span>'
        f'<span class="chip">Last crawl: {last_mod}</span>'
        "</div>"
    )


def build_storage_page() -> gr.Column:
    """Build the storage page as a hideable column."""
    with gr.Column(visible=False) as col:

        # ── Panel 1: Bucket stats ────────────────────────────────────────
        gr.Markdown("### Bucket overview")
        stats_html = gr.HTML("<div class='chip-list'><span class='chip'>Loading…</span></div>")
        refresh_btn = gr.Button("Refresh", size="sm")

        # ── Panel 2: Object list ─────────────────────────────────────────
        gr.Markdown("### Stored results")
        objects_table = gr.Dataframe(
            headers=["job_id", "size", "last_modified"],
            label="Objects",
            interactive=False,
        )

        with gr.Row():
            dl_job_id = gr.Textbox(label="Job ID to download", placeholder="Paste from table above")
            dl_fmt = gr.Radio(["json", "jsonl"], value="json", label="Format")
            dl_btn = gr.Button("Download")
        dl_file = gr.File(label="Downloaded result", visible=False)

        gr.Markdown("---")
        with gr.Row():
            del_job_id = gr.Textbox(label="Job ID to delete", placeholder="Paste from table above")
            del_btn = gr.Button("Delete", variant="stop")
        with gr.Group(visible=False) as confirm_group:
            del_confirm_msg = gr.Markdown("")
            with gr.Row():
                del_cancel_btn = gr.Button("Cancel")
                del_confirm_btn = gr.Button("Confirm delete", variant="stop")
        del_status = gr.Markdown("")

        # ── Panel 3: DuckDB query ────────────────────────────────────────
        gr.Markdown("### Query history")
        with gr.Row():
            hist_seed = gr.Textbox(label="Seed URL", placeholder="e.g. vietnamnet.vn", scale=2)
            hist_goal = gr.Textbox(label="Goal", placeholder="e.g. finance news", scale=2)
            hist_limit = gr.Number(label="Limit", value=20, precision=0, scale=1)
        with gr.Row():
            hist_date_from = gr.Textbox(label="Date from (YYYY-MM-DD)", scale=1)
            hist_date_to = gr.Textbox(label="Date to (YYYY-MM-DD)", scale=1)
            hist_search_btn = gr.Button("Search", variant="primary", scale=1)
        hist_msg = gr.Markdown("")
        hist_table = gr.Dataframe(
            headers=["job_id", "seed_url", "goal", "generated_at", "total_pages"],
            label="Past Crawl Runs",
            interactive=False,
        )
        with gr.Row():
            hist_dl_id = gr.Textbox(label="Job ID to download", placeholder="Paste job_id from table")
            hist_dl_fmt = gr.Radio(["json", "jsonl"], value="json", label="Format")
            hist_dl_btn = gr.Button("Download")
        hist_dl_file = gr.File(label="Downloaded result", visible=False)

        # ── Event handlers ───────────────────────────────────────────────
        async def _load_overview():
            try:
                overview = await get_storage_overview()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 503:
                    return (
                        "<div class='error-text'>Object storage not configured on the engine.</div>",
                        [],
                    )
                return (f"<div class='error-text'>Error: {exc}</div>", [])
            except httpx.RequestError as exc:
                return (f"<div class='error-text'>Engine unreachable: {exc}</div>", [])
            html = _build_stats_html(overview)
            rows = [
                [o["job_id"], _format_size(o["size_bytes"]), o["last_modified"][:19]]
                for o in overview.get("objects", [])
            ]
            return html, rows

        async def _on_download(job_id: str, fmt: str):
            if not job_id.strip():
                return gr.update(visible=False)
            try:
                data = await download_from_storage(job_id.strip(), fmt)
            except httpx.HTTPStatusError as exc:
                raise gr.Error(f"Download failed: {exc.response.status_code}") from exc
            suffix = ".jsonl" if fmt == "jsonl" else ".json"
            path = str(Path(tempfile.gettempdir()) / f"crawl-{uuid4().hex}{suffix}")
            await asyncio.to_thread(Path(path).write_bytes, data)
            return gr.update(value=path, visible=True)

        def _on_delete_click(job_id: str):
            if not job_id.strip():
                return gr.update(visible=False), gr.update(value="")
            msg = f"**Delete `crawl-{job_id.strip()}.json`? This cannot be undone.**"
            return gr.update(visible=True), gr.update(value=msg)

        async def _on_delete_confirm(job_id: str):
            try:
                await delete_stored_result(job_id.strip())
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                msg = "Not found." if status == 404 else f"Error {status}."
                return gr.update(visible=False), gr.update(value=f"**{msg}**"), "", []
            overview = await get_storage_overview()
            rows = [
                [o["job_id"], _format_size(o["size_bytes"]), o["last_modified"][:19]]
                for o in overview.get("objects", [])
            ]
            return (
                gr.update(visible=False),
                gr.update(value=f"Deleted `crawl-{job_id.strip()}.json`."),
                "",
                rows,
            )

        async def _on_search(seed_url, goal, date_from, date_to, limit):
            result = await query_history({
                "seed_url": seed_url or "", "goal": goal or "",
                "date_from": date_from or "", "date_to": date_to or "",
                "limit": int(limit or 20),
            })
            if "error" in result:
                return [], f"**Error:** {result['error']}"
            rows = [
                [r["job_id"], r["seed_url"], r["goal"], r["generated_at"], r["total_pages"]]
                for r in result.get("results", [])
            ]
            return rows, f"{len(rows)} result(s) found." if rows else "No results found."

        refresh_btn.click(fn=_load_overview, outputs=[stats_html, objects_table])
        dl_btn.click(fn=_on_download, inputs=[dl_job_id, dl_fmt], outputs=[dl_file])
        del_btn.click(fn=_on_delete_click, inputs=[del_job_id], outputs=[confirm_group, del_confirm_msg])
        del_cancel_btn.click(fn=lambda: gr.update(visible=False), outputs=[confirm_group])
        del_confirm_btn.click(
            fn=_on_delete_confirm,
            inputs=[del_job_id],
            outputs=[confirm_group, del_status, del_job_id, objects_table],
        )
        hist_search_btn.click(
            fn=_on_search,
            inputs=[hist_seed, hist_goal, hist_date_from, hist_date_to, hist_limit],
            outputs=[hist_table, hist_msg],
        )
        hist_dl_btn.click(fn=_on_download, inputs=[hist_dl_id, hist_dl_fmt], outputs=[hist_dl_file])

    return col
```

- [ ] **Step 4: Run tests**

```bash
uv run python -m pytest tests/gradio/test_ui_storage.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Smoke-test import**

```bash
uv run python -c "from crawl_tool.gradio.ui_storage import build_storage_page; print('ok')"
```

- [ ] **Step 6: Commit**

```bash
git add src/crawl_tool/gradio/ui_storage.py tests/gradio/test_ui_storage.py
git commit -m "feat: add storage page with stats, object list, delete, and DuckDB query"
```

---

## Task 9: App assembly, sidebar nav, and cleanup

**Files:**
- Modify: `src/crawl_tool/gradio/app.py` — full rewrite with sidebar
- Modify: `src/crawl_tool/gradio/dev_ui.py` — update imports
- Delete: `src/crawl_tool/gradio/ui.py`

**Interfaces:**
- Consumes: `build_quick_crawl_page`, `build_advanced_crawl_page`, `build_storage_page`
- Produces: `build_demo() -> gr.Blocks`
- Internal helper (testable): `_switch_page(choice: str) -> list[dict]`

- [ ] **Step 1: Write failing test**

Add to `tests/gradio/test_ui.py` (or a new file):

```python
def test_switch_page_shows_only_selected():
    from crawl_tool.gradio.app import _switch_page
    updates = _switch_page("Advanced Crawl")
    assert updates[0]["visible"] is False   # Quick Crawl hidden
    assert updates[1]["visible"] is True    # Advanced Crawl shown
    assert updates[2]["visible"] is False   # Storage hidden
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run python -m pytest tests/gradio/test_ui.py -k "switch_page" -v
```

Expected: `FAILED` — `cannot import name '_switch_page'`

- [ ] **Step 3: Rewrite `app.py`**

```python
"""Launch the Crawl Tool Gradio interface."""

from __future__ import annotations

import logging

import gradio as gr

from crawl_tool.gradio.ui_advanced_crawl import build_advanced_crawl_page
from crawl_tool.gradio.ui_quick_crawl import build_quick_crawl_page
from crawl_tool.gradio.ui_storage import build_storage_page
from crawl_tool.gradio.ui_styles import CUSTOM_CSS, _RESULT_JS

_NAV_PAGES = ["Quick Crawl", "Advanced Crawl", "Storage"]

_NAV_CSS = """
.nav-radio label { display: none !important; }
.nav-radio .wrap {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.nav-radio .wrap label.svelte-1ixch81 {
  display: flex !important;
  padding: 0.65rem 1rem;
  border-radius: 10px;
  font-weight: 600;
  font-size: 0.9rem;
  cursor: pointer;
  color: var(--crawler-muted);
  transition: all 0.15s ease;
}
.nav-radio .wrap label.svelte-1ixch81:hover {
  background: rgba(201, 79, 45, 0.06);
  color: var(--crawler-ink);
}
.nav-radio input:checked + label.svelte-1ixch81 {
  background: rgba(201, 79, 45, 0.1);
  color: var(--crawler-accent);
}
"""


def _switch_page(choice: str) -> list[dict]:
    return [gr.update(visible=(choice == page)) for page in _NAV_PAGES]


def build_demo() -> gr.Blocks:
    """Build the Gradio multi-page crawler interface."""
    with gr.Blocks(title="VSF Crawl Tool") as demo:
        with gr.Row():
            with gr.Column(scale=1, min_width=180):
                gr.HTML(
                    '<div style="padding: 1.5rem 1rem 1rem;">'
                    '<span style="font-weight: 900; font-size: 1.1rem; color: #18231f;">VSF Crawl Tool</span>'
                    "</div>"
                )
                nav = gr.Radio(
                    _NAV_PAGES,
                    value="Quick Crawl",
                    label="",
                    elem_classes="nav-radio",
                )

            with gr.Column(scale=4):
                quick_col = build_quick_crawl_page()
                advanced_col = build_advanced_crawl_page()
                storage_col = build_storage_page()

        nav.change(
            fn=_switch_page,
            inputs=[nav],
            outputs=[quick_col, advanced_col, storage_col],
        )

    return demo


def main() -> None:
    """Configure logging and launch the web interface."""
    logging.basicConfig(level=logging.INFO)
    build_demo().queue(default_concurrency_limit=1).launch(
        server_name="0.0.0.0",
        server_port=7860,
        css=CUSTOM_CSS + _NAV_CSS,
        js=_RESULT_JS,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Update `dev_ui.py`**

Update the imports in `dev_ui.py`:

```python
# Before:
from crawl_tool.gradio.ui import _RESULT_JS, CUSTOM_CSS, build_demo

# After:
from crawl_tool.gradio.app import build_demo
from crawl_tool.gradio.ui_styles import CUSTOM_CSS, _RESULT_JS
```

Also update the `build_demo()` call — `dev_ui.py` passes `initial_payload` which the new `build_demo()` no longer accepts. Remove that parameter and instead have the dev UI launch without preloaded payload (the payload preload was Advanced Crawl-specific; the new structure makes this harder to support cleanly):

```python
def main() -> None:
    """Launch the crawler UI for development."""
    ...
    logging.basicConfig(level=logging.INFO)
    build_demo().queue(default_concurrency_limit=1).launch(
        css=f"{CUSTOM_CSS}\n{_NAV_CSS}\n{DEV_UI_CSS}",
        head=DEV_UI_HEAD,
        inbrowser=True,
    )
```

Import `_NAV_CSS` from `app.py`:

```python
from crawl_tool.gradio.app import _NAV_CSS, build_demo
from crawl_tool.gradio.ui_styles import CUSTOM_CSS, _RESULT_JS
```

- [ ] **Step 5: Delete `ui.py`**

```bash
git rm src/crawl_tool/gradio/ui.py
```

- [ ] **Step 6: Run full test suite**

```bash
uv run python -m pytest tests/ -m "not integration" -v
```

Expected: all tests pass. If `test_ui.py` has a residual import of `ui`, the update in Task 5 Step 5 handles it.

- [ ] **Step 7: Lint**

```bash
uv run ruff check .
```

Fix any issues found.

- [ ] **Step 8: Commit**

```bash
git add src/crawl_tool/gradio/app.py src/crawl_tool/gradio/dev_ui.py tests/gradio/test_ui.py
git commit -m "feat: assemble sidebar nav and three-page Gradio UI, remove ui.py"
```

---

## Post-implementation verification

- [ ] Run the full unit suite: `uv run python -m pytest tests/ -m "not integration" -q`
  - Expected: all existing tests pass; new tests for storage functions, endpoints, client functions, and page helpers all pass
- [ ] Start the app locally and verify all three pages load:
  ```bash
  ANTHROPIC_API_KEY=sk-... uv run python -m crawl_tool.gradio.app
  ```
  - Navigate to `http://localhost:7860`
  - Switch between Quick Crawl, Advanced Crawl, and Storage via sidebar
  - Quick Crawl: paste a sample prompt, click Parse, verify fields populate
  - Advanced Crawl: verify same layout as before
  - Storage: verify stats load (or 503 banner if MinIO not running)
- [ ] Lint: `uv run ruff check .`
