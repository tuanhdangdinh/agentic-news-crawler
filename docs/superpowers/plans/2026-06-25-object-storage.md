# Object Storage with Queryable History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every completed crawl result to MinIO, and expose a structured query API (HTTP + Gradio UI + CLI) backed by DuckDB reading JSON files directly from MinIO.

**Architecture:** On job completion `run_job()` in `service.py` uploads the result payload (with `job_id` injected into `meta`) to MinIO as `crawl-{job_id}.json`. A new `/query` endpoint runs a DuckDB in-memory connection with `httpfs` configured for MinIO and queries across all stored files. A `/storage/{job_id}` endpoint fetches individual files from MinIO for download.

**Tech Stack:** `minio` (Python SDK, sync — wrapped in `asyncio.to_thread`), `duckdb` (in-process SQL with `httpfs` extension, sync — wrapped in `asyncio.to_thread`), MinIO docker image in compose.

## Global Constraints

- All I/O is async; use `asyncio.to_thread` for sync `minio` and `duckdb` calls — never call them directly in async context.
- Credentials never appear in logs or API responses — mirror `ProxyRotator` pattern.
- MinIO is optional; if `MINIO_ENDPOINT` is unset, `StorageSettings.enabled` is `False` and all storage paths are skipped silently; `/query` and `/storage/*` return HTTP 503.
- Line length 100; ruff rules E/F/I/UP/B/SIM; all public functions require type hints; use `X | Y` not `Optional[X]`.
- Run tests with `uv run python -m pytest`, lint with `uv run ruff check .`.
- Commit messages: subject line only, Conventional Commits format, no body, no Co-Authored-By.
- Spec: `docs/superpowers/specs/2026-06-25-object-storage-design.md`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `src/crawl_tool/engine/storage.py` | MinIO client, `StorageSettings`, `put_result`, `get_result` |
| Create | `src/crawl_tool/engine/query.py` | DuckDB runner, `_execute_query`, `run_query` |
| Modify | `src/crawl_tool/engine/contract.py` | Add `CrawlQuery`, `CrawlSummary` Pydantic models |
| Modify | `src/crawl_tool/engine/service.py` | Upload on completion; add `/query`, `/storage/{id}` endpoints |
| Modify | `src/crawl_tool/gradio/client.py` | Add `query_history`, `download_from_storage` |
| Modify | `src/crawl_tool/gradio/ui.py` | Add History tab |
| Modify | `src/crawl_tool/engine/cli.py` | Add `query` subcommand via pre-dispatch |
| Modify | `docker/docker-compose.yml` | Add MinIO service |
| Modify | `pyproject.toml` | Add `minio`, `duckdb` dependencies |
| Create | `tests/engine/test_storage.py` | Unit tests for `put_result`, `get_result` |
| Create | `tests/engine/test_query.py` | Unit tests for `_execute_query` using local fixtures |

---

### Task 1: Infrastructure — pyproject.toml and docker-compose

**Files:**
- Modify: `pyproject.toml`
- Modify: `docker/docker-compose.yml`

**Interfaces:**
- Produces: `minio` and `duckdb` importable in subsequent tasks; MinIO service available at `localhost:9000`

- [ ] **Step 1: Add dependencies to pyproject.toml**

Open `pyproject.toml`. In the `dependencies` list (after `httpx>=0.27.0`), add:

```toml
    "minio>=7.2.0",
    "duckdb>=1.1.0",
```

- [ ] **Step 2: Install the new dependencies**

```bash
uv sync
```

Expected: resolves without error; `minio` and `duckdb` appear in the lock file.

- [ ] **Step 3: Verify imports work**

```bash
uv run python -c "import minio; import duckdb; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 4: Add MinIO service to docker-compose.yml**

Open `docker/docker-compose.yml`. Replace the entire file content with:

```yaml
services:
  engine:
    build:
      context: ..
      dockerfile: docker/Dockerfile.engine
    environment:
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY}
      CORS_ALLOW_ORIGINS: ${CORS_ALLOW_ORIGINS:-*}
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY:-minioadmin}
      MINIO_SECRET_KEY: ${MINIO_SECRET_KEY:-minioadmin}
      MINIO_BUCKET: ${MINIO_BUCKET:-crawl-results}
      MINIO_SECURE: "false"
    ports:
      - "8000:8000"
    depends_on:
      - minio

  ui:
    build:
      context: ..
      dockerfile: docker/Dockerfile.gradio
    environment:
      ENGINE_URL: http://engine:8000
    ports:
      - "7860:7860"
    depends_on:
      - engine

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY:-minioadmin}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY:-minioadmin}
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data

volumes:
  minio_data:
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml docker/docker-compose.yml uv.lock
git commit -m "chore: add minio and duckdb dependencies, add minio to docker-compose"
```

---

### Task 2: engine/storage.py

**Files:**
- Create: `src/crawl_tool/engine/storage.py`
- Create: `tests/engine/test_storage.py`

**Interfaces:**
- Produces:
  - `StorageSettings` — dataclass with `.enabled: bool`, `.from_env() -> StorageSettings`
  - `put_result(job_id: str, payload: dict, settings: StorageSettings) -> None` — async, injects `job_id` into `payload["meta"]` copy before upload
  - `get_result(job_id: str, settings: StorageSettings) -> bytes | None` — async, returns `None` on 404

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_storage.py`:

```python
"""Tests for engine/storage.py."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from crawl_tool.engine.storage import (
    StorageSettings,
    _put_result_sync,
    _get_result_sync,
)


def _settings() -> StorageSettings:
    return StorageSettings(
        endpoint="localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        bucket="crawl-results",
        secure=False,
    )


def test_storage_settings_disabled_when_no_endpoint():
    s = StorageSettings(endpoint="", access_key="", secret_key="", bucket="b", secure=False)
    assert not s.enabled


def test_storage_settings_enabled_when_endpoint_set():
    assert _settings().enabled


def test_storage_settings_from_env(monkeypatch):
    monkeypatch.setenv("MINIO_ENDPOINT", "myhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "key")
    monkeypatch.setenv("MINIO_SECRET_KEY", "secret")
    monkeypatch.setenv("MINIO_BUCKET", "mybucket")
    monkeypatch.setenv("MINIO_SECURE", "true")
    s = StorageSettings.from_env()
    assert s.endpoint == "myhost:9000"
    assert s.bucket == "mybucket"
    assert s.secure is True


def test_put_result_injects_job_id_into_meta():
    """put_result must inject job_id into the stored meta without mutating original payload."""
    uploaded: dict = {}

    mock_client = MagicMock()
    mock_client.bucket_exists.return_value = True

    def capture_put(bucket_name, object_name, data, length, content_type):
        uploaded["body"] = json.loads(data.read())

    mock_client.put_object.side_effect = capture_put

    payload = {"meta": {"seed_url": "https://example.com", "total_pages": 1}, "pages": []}

    with patch("crawl_tool.engine.storage._make_client", return_value=mock_client):
        _put_result_sync("abc123", payload, _settings())

    assert uploaded["body"]["meta"]["job_id"] == "abc123"
    assert uploaded["body"]["meta"]["seed_url"] == "https://example.com"
    # original payload is not mutated
    assert "job_id" not in payload["meta"]


def test_put_result_creates_bucket_if_missing():
    mock_client = MagicMock()
    mock_client.bucket_exists.return_value = False

    with patch("crawl_tool.engine.storage._make_client", return_value=mock_client):
        _put_result_sync("xyz", {"meta": {}, "pages": []}, _settings())

    mock_client.make_bucket.assert_called_once_with("crawl-results")


def test_get_result_returns_bytes_on_success():
    mock_response = MagicMock()
    mock_response.read.return_value = b'{"meta": {}}'
    mock_client = MagicMock()
    mock_client.get_object.return_value = mock_response

    with patch("crawl_tool.engine.storage._make_client", return_value=mock_client):
        result = _get_result_sync("abc123", _settings())

    assert result == b'{"meta": {}}'
    mock_response.close.assert_called_once()


def test_get_result_returns_none_on_missing_key():
    from minio.error import S3Error

    mock_client = MagicMock()
    err = S3Error("NoSuchKey", "not found", "url", "req", "host", MagicMock())
    mock_client.get_object.side_effect = err

    with patch("crawl_tool.engine.storage._make_client", return_value=mock_client):
        result = _get_result_sync("missing", _settings())

    assert result is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run python -m pytest tests/engine/test_storage.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` for `crawl_tool.engine.storage`.

- [ ] **Step 3: Create src/crawl_tool/engine/storage.py**

```python
"""MinIO object storage client for persisting crawl results."""

from __future__ import annotations

import asyncio
import io
import json
import os
from dataclasses import dataclass

import structlog
from minio import Minio
from minio.error import S3Error

logger = structlog.get_logger(__name__)


@dataclass
class StorageSettings:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool

    @classmethod
    def from_env(cls) -> StorageSettings:
        return cls(
            endpoint=os.environ.get("MINIO_ENDPOINT", ""),
            access_key=os.environ.get("MINIO_ACCESS_KEY", ""),
            secret_key=os.environ.get("MINIO_SECRET_KEY", ""),
            bucket=os.environ.get("MINIO_BUCKET", "crawl-results"),
            secure=os.environ.get("MINIO_SECURE", "false").lower() == "true",
        )

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)


def _make_client(settings: StorageSettings) -> Minio:
    return Minio(
        endpoint=settings.endpoint,
        access_key=settings.access_key,
        secret_key=settings.secret_key,
        secure=settings.secure,
    )


def _put_result_sync(job_id: str, payload: dict, settings: StorageSettings) -> None:
    client = _make_client(settings)
    if not client.bucket_exists(settings.bucket):
        client.make_bucket(settings.bucket)
    payload_copy = {**payload, "meta": {**payload.get("meta", {}), "job_id": job_id}}
    data = json.dumps(payload_copy, ensure_ascii=False).encode()
    client.put_object(
        bucket_name=settings.bucket,
        object_name=f"crawl-{job_id}.json",
        data=io.BytesIO(data),
        length=len(data),
        content_type="application/json",
    )
    logger.debug("uploaded result", job_id=job_id, bucket=settings.bucket)


def _get_result_sync(job_id: str, settings: StorageSettings) -> bytes | None:
    client = _make_client(settings)
    try:
        response = client.get_object(settings.bucket, f"crawl-{job_id}.json")
        try:
            return response.read()
        finally:
            response.close()
    except S3Error as exc:
        if exc.code == "NoSuchKey":
            return None
        raise


async def put_result(job_id: str, payload: dict, settings: StorageSettings) -> None:
    """Upload result payload to MinIO as crawl-{job_id}.json, injecting job_id into meta."""
    await asyncio.to_thread(_put_result_sync, job_id, payload, settings)


async def get_result(job_id: str, settings: StorageSettings) -> bytes | None:
    """Fetch raw bytes for crawl-{job_id}.json from MinIO. Returns None if not found."""
    return await asyncio.to_thread(_get_result_sync, job_id, settings)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run python -m pytest tests/engine/test_storage.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Run lint**

```bash
uv run ruff check src/crawl_tool/engine/storage.py tests/engine/test_storage.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/crawl_tool/engine/storage.py tests/engine/test_storage.py
git commit -m "feat: add MinIO storage module with put_result and get_result"
```

---

### Task 3: contract.py models + engine/query.py

**Files:**
- Modify: `src/crawl_tool/engine/contract.py`
- Create: `src/crawl_tool/engine/query.py`
- Create: `tests/engine/test_query.py`

**Interfaces:**
- Consumes: `StorageSettings` from `storage.py`
- Produces:
  - `CrawlQuery` — Pydantic model in `contract.py`: `seed_url: str = ""`, `goal: str = ""`, `date_from: str = ""`, `date_to: str = ""`, `limit: int = 20`
  - `CrawlSummary` — Pydantic model in `contract.py`: `job_id: str`, `seed_url: str`, `goal: str`, `generated_at: str`, `total_pages: int`, `successful: int`, `failed: int`
  - `_execute_query(conn, path: str, query: CrawlQuery) -> list[dict]` — pure DuckDB logic, testable without S3
  - `run_query(query: CrawlQuery, settings: StorageSettings) -> list[CrawlSummary]` — async public API

- [ ] **Step 1: Add CrawlQuery and CrawlSummary to contract.py**

Open `src/crawl_tool/engine/contract.py`. At the end of the file, after the `JobResult` class, append:

```python


class CrawlQuery(BaseModel):
    """Structured filter for querying stored crawl history."""

    seed_url: str = ""
    goal: str = ""
    date_from: str = ""
    date_to: str = ""
    limit: int = Field(default=20, ge=1, le=500)


class CrawlSummary(BaseModel):
    """Lightweight metadata record returned from a history query."""

    job_id: str
    seed_url: str
    goal: str
    generated_at: str
    total_pages: int
    successful: int
    failed: int
```

- [ ] **Step 2: Write failing tests for query.py**

Create `tests/engine/test_query.py`:

```python
"""Tests for engine/query.py — _execute_query."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

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
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
uv run python -m pytest tests/engine/test_query.py -v
```

Expected: `ImportError` for `crawl_tool.engine.query`.

- [ ] **Step 4: Create src/crawl_tool/engine/query.py**

```python
"""DuckDB-based query runner for crawl result history stored in MinIO."""

from __future__ import annotations

import asyncio

import duckdb
import structlog

from crawl_tool.engine.contract import CrawlQuery, CrawlSummary
from crawl_tool.engine.storage import StorageSettings

logger = structlog.get_logger(__name__)

_COLS = ["job_id", "seed_url", "goal", "generated_at", "total_pages", "successful", "failed"]


def _configure_s3(conn: duckdb.DuckDBPyConnection, settings: StorageSettings) -> None:
    conn.execute("INSTALL httpfs")
    conn.execute("LOAD httpfs")
    conn.execute("SET s3_region='us-east-1'")
    conn.execute(f"SET s3_url_style='path'")
    conn.execute(f"SET s3_endpoint='{settings.endpoint}'")
    conn.execute(f"SET s3_access_key_id='{settings.access_key}'")
    conn.execute(f"SET s3_secret_access_key='{settings.secret_key}'")
    conn.execute(f"SET s3_use_ssl={'true' if settings.secure else 'false'}")


def _execute_query(
    conn: duckdb.DuckDBPyConnection, path: str, query: CrawlQuery
) -> list[dict]:
    conditions: list[str] = []
    params: list[str | int] = []

    if query.seed_url:
        conditions.append(
            "LOWER(CAST(meta.seed_url AS VARCHAR)) LIKE LOWER(CONCAT('%', ?, '%'))"
        )
        params.append(query.seed_url)
    if query.goal:
        conditions.append(
            "LOWER(CAST(meta.goal AS VARCHAR)) LIKE LOWER(CONCAT('%', ?, '%'))"
        )
        params.append(query.goal)
    if query.date_from:
        conditions.append("meta.generated_at >= ?")
        params.append(query.date_from)
    if query.date_to:
        conditions.append("meta.generated_at <= ?")
        params.append(query.date_to)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(query.limit)

    sql = f"""
        SELECT
            CAST(meta.job_id AS VARCHAR)        AS job_id,
            CAST(meta.seed_url AS VARCHAR)      AS seed_url,
            CAST(meta.goal AS VARCHAR)          AS goal,
            CAST(meta.generated_at AS VARCHAR)  AS generated_at,
            CAST(meta.total_pages AS INTEGER)   AS total_pages,
            CAST(meta.successful AS INTEGER)    AS successful,
            CAST(meta.failed AS INTEGER)        AS failed
        FROM read_json('{path}')
        {where}
        LIMIT ?
    """
    rows = conn.execute(sql, params).fetchall()
    return [dict(zip(_COLS, row)) for row in rows]


def _run_query_sync(query: CrawlQuery, settings: StorageSettings) -> list[dict]:
    conn = duckdb.connect()
    _configure_s3(conn, settings)
    path = f"s3://{settings.bucket}/crawl-*.json"
    return _execute_query(conn, path, query)


async def run_query(query: CrawlQuery, settings: StorageSettings) -> list[CrawlSummary]:
    """Run a structured query against crawl result history in MinIO."""
    rows = await asyncio.to_thread(_run_query_sync, query, settings)
    return [CrawlSummary(**row) for row in rows]
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
uv run python -m pytest tests/engine/test_query.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 6: Run lint**

```bash
uv run ruff check src/crawl_tool/engine/contract.py src/crawl_tool/engine/query.py tests/engine/test_query.py
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/crawl_tool/engine/contract.py src/crawl_tool/engine/query.py tests/engine/test_query.py
git commit -m "feat: add CrawlQuery/CrawlSummary models and DuckDB query runner"
```

---

### Task 4: service.py — upload on completion + new endpoints

**Files:**
- Modify: `src/crawl_tool/engine/service.py`
- Modify: `tests/engine/test_service.py`

**Interfaces:**
- Consumes:
  - `StorageSettings.from_env()`, `put_result(job_id, payload, settings)`, `get_result(job_id, settings)` from `storage.py`
  - `run_query(query, settings)` from `query.py`
  - `CrawlQuery`, `CrawlSummary` from `contract.py`
- Produces:
  - `POST /query` → `list[CrawlSummary]` (503 if `not settings.enabled`)
  - `GET /storage/{job_id}` → raw JSON bytes with `Content-Disposition` attachment (404 / 503)
  - `run_job()` uploads result to MinIO after `job.status = JobStatus.done`

- [ ] **Step 1: Write failing tests**

Open `tests/engine/test_service.py`. After the existing tests, append:

```python
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
```

- [ ] **Step 2: Run new tests to confirm they fail**

```bash
uv run python -m pytest tests/engine/test_service.py -v -k "storage or query"
```

Expected: most fail with `404` or `AttributeError` — endpoints don't exist yet.

- [ ] **Step 3: Update service.py**

Open `src/crawl_tool/engine/service.py`. Apply these changes:

**3a.** Add imports at the top (after existing imports):

```python
from crawl_tool.engine.contract import (
    CrawlQuery,
    CrawlSummary,
    ...  # keep existing imports
)
from crawl_tool.engine.query import run_query
from crawl_tool.engine.storage import StorageSettings, get_result, put_result
```

Replace the existing `from crawl_tool.engine.contract import (...)` block with:

```python
from crawl_tool.engine.contract import (
    CrawlQuery,
    CrawlSummary,
    CrawlRequest,
    JobCreated,
    JobProgress,
    JobResult,
    JobStatus,
)
from crawl_tool.engine.query import run_query
from crawl_tool.engine.storage import StorageSettings, get_result, put_result
```

**3b.** In `create_app()`, add `StorageSettings` initialization right after `run_lock = asyncio.Lock()`:

```python
    storage_settings = StorageSettings.from_env()
```

**3c.** In `run_job()` (the inner closure), after `job.status = JobStatus.done`, add the upload call:

```python
                job.payload = await execute(job.request, job.state)
                job.status = JobStatus.done
                if storage_settings.enabled:
                    try:
                        await put_result(job_id, job.payload, storage_settings)
                    except Exception as upload_exc:  # noqa: BLE001
                        logger.warning("storage upload failed", job_id=job_id, error=str(upload_exc))
```

**3d.** Add the two new endpoints inside `create_app()`, before `return app`:

```python
    @app.post("/query")
    async def query_history(query: CrawlQuery) -> list[CrawlSummary]:
        """Query stored crawl history in MinIO using structured filters."""
        if not storage_settings.enabled:
            raise HTTPException(status_code=503, detail="storage not configured")
        return await run_query(query, storage_settings)

    @app.get("/storage/{job_id}")
    async def get_stored_result(job_id: str, format: str = "json") -> Response:
        """Fetch a completed crawl result directly from object storage."""
        if not storage_settings.enabled:
            raise HTTPException(status_code=503, detail="storage not configured")
        raw = await get_result(job_id, storage_settings)
        if raw is None:
            raise HTTPException(status_code=404, detail="result not found in storage")
        if format == "jsonl":
            import json as _json
            payload = _json.loads(raw)
            body = serialize_payload(payload, "jsonl").encode()
            media_type = "application/x-ndjson"
            filename = f"crawl-{job_id}.jsonl"
        else:
            body = raw
            media_type = "application/json"
            filename = f"crawl-{job_id}.json"
        return Response(
            content=body,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
```

- [ ] **Step 4: Run new tests to confirm they pass**

```bash
uv run python -m pytest tests/engine/test_service.py -v -k "storage or query"
```

Expected: all 5 new tests pass.

- [ ] **Step 5: Run full service test suite to check for regressions**

```bash
uv run python -m pytest tests/engine/test_service.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Run lint**

```bash
uv run ruff check src/crawl_tool/engine/service.py
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/crawl_tool/engine/service.py tests/engine/test_service.py
git commit -m "feat: upload results to MinIO on job completion, add /query and /storage endpoints"
```

---

### Task 5: Gradio History tab

**Files:**
- Modify: `src/crawl_tool/gradio/client.py`
- Modify: `src/crawl_tool/gradio/ui.py`

**Interfaces:**
- Consumes: `POST /query` and `GET /storage/{job_id}` from the engine
- Produces:
  - `query_history(filters: dict, *, base_url: str) -> dict` — calls `POST /query`, returns `{"results": [...]}` or `{"error": "..."}`
  - `download_from_storage(job_id: str, fmt: str, *, base_url: str) -> bytes` — calls `GET /storage/{job_id}`
  - History tab in `build_demo()` with filter inputs, search button, results dataframe, job_id input, download button

- [ ] **Step 1: Add client functions to gradio/client.py**

Open `src/crawl_tool/gradio/client.py`. After the `download_result` function, append:

```python

async def query_history(
    filters: dict,
    *,
    base_url: str = ENGINE_URL,
) -> dict:
    """Query crawl history via the engine's /query endpoint.

    Args:
        filters: CrawlQuery fields as a plain dict.
        base_url: Crawl engine base URL.

    Returns:
        Dict with "results" key (list of CrawlSummary dicts) or "error" key on failure.
    """
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        try:
            response = await http.post("/query", json=filters)
            if response.status_code == 503:
                return {"error": "Object storage is not configured on the engine."}
            response.raise_for_status()
            return {"results": response.json()}
        except httpx.HTTPStatusError as exc:
            return {"error": f"Query failed: {exc.response.status_code}"}
        except httpx.RequestError as exc:
            return {"error": f"Engine unreachable: {exc}"}


async def download_from_storage(
    job_id: str,
    fmt: str = "json",
    *,
    base_url: str = ENGINE_URL,
) -> bytes:
    """Download a result from object storage.

    Args:
        job_id: Crawl job identifier.
        fmt: Requested result format ("json" or "jsonl").
        base_url: Crawl engine base URL.

    Returns:
        Serialized result bytes.
    """
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as http:
        response = await http.get(f"/storage/{job_id}", params={"format": fmt})
        response.raise_for_status()
        return response.content
```

- [ ] **Step 2: Add History tab to ui.py**

Open `src/crawl_tool/gradio/ui.py`. 

**2a.** Add the new client imports at the top of the file. Find the existing import:

```python
from crawl_tool.gradio.client import download_result, poll_until_done, start_crawl
```

Replace with:

```python
from crawl_tool.gradio.client import (
    download_from_storage,
    download_result,
    poll_until_done,
    query_history,
    start_crawl,
)
```

**2b.** Find the existing `gr.Tabs()` block near the bottom of `build_demo()`:

```python
        with gr.Tabs():
            with gr.TabItem("Extracted Data"):
```

Inside `gr.Tabs()`, after the last existing `TabItem`, add the History tab. Find the closing of the last `TabItem` and append:

```python
            with gr.TabItem("History"):
                with gr.Row():
                    hist_seed_url = gr.Textbox(
                        label="Seed URL", placeholder="e.g. vietnamnet.vn", scale=2
                    )
                    hist_goal = gr.Textbox(
                        label="Goal", placeholder="e.g. finance news", scale=2
                    )
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
                    hist_job_id_input = gr.Textbox(
                        label="Job ID to download", placeholder="Paste job_id from table above"
                    )
                    hist_fmt = gr.Radio(["json", "jsonl"], value="json", label="Format")
                    hist_download_btn = gr.Button("Download")
                hist_file = gr.File(label="Downloaded result", visible=False)
```

**2c.** After the `gr.Tabs()` block (but still inside `build_demo()` before `return demo`), add the event handlers:

```python
        async def _search_history(seed_url, goal, date_from, date_to, limit):
            result = await query_history({
                "seed_url": seed_url or "",
                "goal": goal or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
                "limit": int(limit or 20),
            })
            if "error" in result:
                return [], f"**Error:** {result['error']}"
            rows = [
                [r["job_id"], r["seed_url"], r["goal"], r["generated_at"], r["total_pages"]]
                for r in result.get("results", [])
            ]
            msg = f"{len(rows)} result(s) found." if rows else "No results found."
            return rows, msg

        hist_search_btn.click(
            _search_history,
            inputs=[hist_seed_url, hist_goal, hist_date_from, hist_date_to, hist_limit],
            outputs=[hist_table, hist_msg],
        )

        async def _download_history(job_id, fmt):
            if not job_id:
                return gr.update(visible=False)
            import tempfile, os
            data = await download_from_storage(job_id.strip(), fmt)
            suffix = f".{fmt}" if fmt == "jsonl" else ".json"
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix, prefix=f"crawl-{job_id}-"
            )
            tmp.write(data)
            tmp.close()
            return gr.update(value=tmp.name, visible=True)

        hist_download_btn.click(
            _download_history,
            inputs=[hist_job_id_input, hist_fmt],
            outputs=[hist_file],
        )
```

- [ ] **Step 3: Verify the Gradio app starts without error**

```bash
uv run python -c "from crawl_tool.gradio.ui import build_demo; build_demo(); print('ok')"
```

Expected: prints `ok` with no import or construction errors.

- [ ] **Step 4: Run existing Gradio tests**

```bash
uv run python -m pytest tests/gradio/ -v
```

Expected: all pass.

- [ ] **Step 5: Run lint**

```bash
uv run ruff check src/crawl_tool/gradio/client.py src/crawl_tool/gradio/ui.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/crawl_tool/gradio/client.py src/crawl_tool/gradio/ui.py
git commit -m "feat: add History tab to Gradio UI with query and download from storage"
```

---

### Task 6: CLI query subcommand

**Files:**
- Modify: `src/crawl_tool/engine/cli.py`

**Interfaces:**
- Consumes: `POST /query` via `httpx`; `ENGINE_URL` env var (default `http://localhost:8000`)
- Produces: `crawl-tool query [--seed-url STR] [--goal STR] [--date-from DATE] [--date-to DATE] [--limit N] [--engine-url URL]` — prints results as an ASCII table or error message

- [ ] **Step 1: Write failing test**

Open `tests/engine/test_main_build_parser.py`. Append:

```python
def test_build_query_parser_accepts_all_flags():
    from crawl_tool.engine.cli import build_query_parser
    args = build_query_parser().parse_args([
        "--seed-url", "vietnamnet.vn",
        "--goal", "finance",
        "--date-from", "2026-06-01",
        "--date-to", "2026-06-30",
        "--limit", "5",
        "--engine-url", "http://myhost:8000",
    ])
    assert args.seed_url == "vietnamnet.vn"
    assert args.goal == "finance"
    assert args.date_from == "2026-06-01"
    assert args.date_to == "2026-06-30"
    assert args.limit == 5
    assert args.engine_url == "http://myhost:8000"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
uv run python -m pytest tests/engine/test_main_build_parser.py::test_build_query_parser_accepts_all_flags -v
```

Expected: `ImportError` — `build_query_parser` doesn't exist yet.

- [ ] **Step 3: Add query subcommand to cli.py**

Open `src/crawl_tool/engine/cli.py`. 

**3a.** Add `import os` and `import sys` to the imports at the top (alongside existing imports).

**3b.** Add `build_query_parser` and `run_query_cmd` functions before `main()`:

```python
def build_query_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the query subcommand."""
    parser = argparse.ArgumentParser(
        prog="crawl-tool query",
        description="Query stored crawl history.",
    )
    parser.add_argument("--seed-url", default="", help="Filter by seed URL substring")
    parser.add_argument("--goal", default="", help="Filter by goal substring")
    parser.add_argument("--date-from", default="", metavar="DATE", help="From date (YYYY-MM-DD)")
    parser.add_argument("--date-to", default="", metavar="DATE", help="To date (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=20, help="Maximum results (default: 20)")
    parser.add_argument(
        "--engine-url",
        default=os.environ.get("ENGINE_URL", "http://localhost:8000"),
        help="Engine base URL",
    )
    return parser


async def run_query_cmd(args: argparse.Namespace) -> None:
    """Call POST /query and print results as an ASCII table."""
    import httpx

    filters = {
        "seed_url": args.seed_url,
        "goal": args.goal,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "limit": args.limit,
    }
    async with httpx.AsyncClient(base_url=args.engine_url, timeout=30.0) as client:
        try:
            resp = await client.post("/query", json=filters)
        except httpx.RequestError as exc:
            print(f"error: engine unreachable — {exc}")
            return
    if resp.status_code == 503:
        print("error: object storage is not configured on the engine")
        return
    if resp.status_code != 200:
        print(f"error: engine returned {resp.status_code}")
        return

    results = resp.json()
    if not results:
        print("no results found")
        return

    col_widths = {
        "job_id": 32,
        "seed_url": 30,
        "goal": 24,
        "generated_at": 25,
        "total_pages": 11,
    }
    header = (
        f"{'job_id':<{col_widths['job_id']}} "
        f"{'seed_url':<{col_widths['seed_url']}} "
        f"{'goal':<{col_widths['goal']}} "
        f"{'generated_at':<{col_widths['generated_at']}} "
        f"{'total_pages':<{col_widths['total_pages']}}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r['job_id']:<{col_widths['job_id']}} "
            f"{str(r['seed_url'])[:col_widths['seed_url']]:<{col_widths['seed_url']}} "
            f"{str(r['goal'])[:col_widths['goal']]:<{col_widths['goal']}} "
            f"{str(r['generated_at'])[:col_widths['generated_at']]:<{col_widths['generated_at']}} "
            f"{r['total_pages']:<{col_widths['total_pages']}}"
        )
```

**3c.** Replace the existing `main()` function:

```python
def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate command."""
    if len(sys.argv) > 1 and sys.argv[1] == "query":
        query_args = build_query_parser().parse_args(sys.argv[2:])
        asyncio.run(run_query_cmd(query_args))
    else:
        parser = build_parser()
        args = parser.parse_args()
        asyncio.run(run(args))
```

- [ ] **Step 4: Run the new test to confirm it passes**

```bash
uv run python -m pytest tests/engine/test_main_build_parser.py::test_build_query_parser_accepts_all_flags -v
```

Expected: PASS.

- [ ] **Step 5: Run full parser test suite to check for regressions**

```bash
uv run python -m pytest tests/engine/test_main_build_parser.py tests/engine/test_main_run.py -v
```

Expected: all pass.

- [ ] **Step 6: Run full test suite**

```bash
uv run python -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 7: Run lint**

```bash
uv run ruff check src/crawl_tool/engine/cli.py
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add src/crawl_tool/engine/cli.py tests/engine/test_main_build_parser.py
git commit -m "feat: add crawl-tool query subcommand for history search"
```
