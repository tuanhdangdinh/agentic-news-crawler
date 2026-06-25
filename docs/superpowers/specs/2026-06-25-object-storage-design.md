# Design: Object Storage with Queryable History

**Prepared:** 2026-06-25

**Revision history:**
- Initial draft: MinIO + DuckDB httpfs design for durable crawl result storage and structured query API
- Rev 2: Fix job_id injection, MinIO httpfs connection settings, status filter removal, run_job() location, doc style

---

## Overview

Crawl results currently live only in an in-memory `dict` inside the engine service with a 1-hour
TTL. A service restart or a late poll loses the result permanently. This design adds MinIO as a
durable object store for crawl result files, and DuckDB as a query layer that reads those files
directly from MinIO — giving users a permanent, searchable history of all crawl runs.

---

## Problem

- The engine stores job results in memory with `JOB_TTL_SECONDS = 3600`. Restart the container
  or poll after the TTL → result is gone.
- The `artifacts/` directory contains hand-saved samples — evidence that users are already
  manually preserving outputs because nothing else does.
- There is no way to list, search, or re-download past crawl runs.

---

## Goals

- Persist every completed crawl result to MinIO as a durable JSON file.
- Expose a structured query API so users can filter past runs by seed URL, goal, and date.
- Surface query and download in the Gradio UI (History tab) and CLI (`query` subcommand).
- Keep MinIO optional — if unconfigured, the engine behaves exactly as today.

---

## Non-Goals

- Do not replace the in-memory job store or the existing 1-hour TTL.
- Do not expose raw SQL to users.
- Do not store raw HTML or `raw_markdown` (already stripped by `output.py`).
- Do not require MinIO for the engine to start or run crawls.
- Do not filter by job status in v1 — only completed jobs are uploaded, so status is always `done`.

---

## Architecture

```text
Job completes (service.py run_job)
     │
     ▼
inject job_id into payload.meta → storage.put(job_id, payload)
                                          │
                                          ▼
                                    MinIO bucket
                                  crawl-{job_id}.json
                                  (meta.job_id = job_id)
                                          │
                              ┌───────────┴───────────┐
                              ▼                       ▼
                       POST /query            GET /storage/{job_id}
                       (DuckDB httpfs)        (direct MinIO fetch)
                              │                       │
                        Gradio UI               Gradio UI
                        CLI query              CLI download
```

---

## Components

### `engine/storage.py`

Owns the MinIO client. Reads configuration from environment:

| Env var | Default | Purpose |
|---|---|---|
| `MINIO_ENDPOINT` | — | MinIO host:port, e.g. `localhost:9000` (unset = storage disabled) |
| `MINIO_ACCESS_KEY` | — | Access key |
| `MINIO_SECRET_KEY` | — | Secret key |
| `MINIO_BUCKET` | `crawl-results` | Bucket name |
| `MINIO_SECURE` | `false` | Set `true` for HTTPS; local compose uses plain HTTP |

Public interface:

```python
class StorageSettings:
    @classmethod
    def from_env(cls) -> StorageSettings: ...
    @property
    def enabled(self) -> bool: ...

async def put_result(job_id: str, payload: dict, settings: StorageSettings) -> None:
    """Inject job_id into payload.meta, then upload as crawl-{job_id}.json."""

async def get_result(job_id: str, settings: StorageSettings) -> bytes | None:
    """Fetch raw bytes for crawl-{job_id}.json from MinIO. Returns None if not found."""
```

`put_result` mutates a shallow copy of `payload["meta"]` to add `job_id` before serializing —
the in-memory payload in the service is not modified. The `minio` Python client is sync; all
calls are wrapped in `asyncio.to_thread`. Credentials never appear in logs.

### `engine/query.py`

Owns the DuckDB query runner. On each query it opens an in-memory DuckDB connection, loads the
`httpfs` extension, and configures it explicitly for MinIO:

```python
conn.execute("SET s3_endpoint = ?", [settings.endpoint])          # host:port
conn.execute("SET s3_url_style = 'path'")                         # MinIO requires path-style
conn.execute("SET s3_use_ssl = ?", [str(settings.secure).lower()])
conn.execute("SET s3_access_key_id = ?", [settings.access_key])
conn.execute("SET s3_secret_access_key = ?", [settings.secret_key])
conn.execute("SET s3_region = 'us-east-1'")                       # MinIO ignores region but httpfs requires it
```

Queries run against `read_json('s3://{bucket}/crawl-*.json', columns={...})`.

Structured filter model:

```python
class CrawlQuery(BaseModel):
    seed_url: str = ""    # substring match on meta.seed_url
    goal: str = ""        # substring match on meta.goal
    date_from: str = ""   # ISO date, filter on meta.generated_at
    date_to: str = ""     # ISO date, filter on meta.generated_at
    limit: int = 20
```

Returns a list of lightweight metadata records — not full page content:

```python
class CrawlSummary(BaseModel):
    job_id: str           # from meta.job_id injected at upload time
    seed_url: str
    goal: str
    generated_at: str
    total_pages: int
    successful: int
    failed: int
```

DuckDB runs in `asyncio.to_thread`.

### `engine/service.py` — upload on completion and new endpoints

`run_job()` (defined inside `create_app()` in `service.py`) calls `put_result(job_id, payload,
settings)` after setting `job.status = JobStatus.done`. Upload failures are logged as warnings
and do not affect job status — the result remains available in memory within the TTL.

**`POST /query`**

- Accepts `CrawlQuery` body.
- Returns `list[CrawlSummary]`.
- Returns `503` if storage is not configured.

**`GET /storage/{job_id}`**

- Fetches `crawl-{job_id}.json` from MinIO.
- Supports `?format=jsonl` (re-serializes via `serialize_payload`).
- Returns `404` if not found, `503` if storage not configured.
- The existing `/crawl/{job_id}/result` endpoint is unchanged.

### `gradio/` — History tab

New tab in the Gradio app:

- Filter fields: Seed URL, Goal, Date from, Date to, Limit
- "Search" button → `POST /query` → populates results dataframe
- Results table: job_id, seed_url, goal, generated_at, total_pages
- "Download JSON" button per row → `GET /storage/{job_id}`

### `engine/cli.py` — `query` subcommand

```bash
crawl-tool query --seed-url vietnamnet.vn --date-from 2026-06-01 --limit 10
```

Calls `POST /query` against `ENGINE_URL` (env var, default `http://localhost:8000`). Prints
results as an ASCII table to stdout.

### `docker/docker-compose.yml`

New `minio` service:

```yaml
minio:
  image: minio/minio
  command: server /data --console-address ":9001"
  environment:
    MINIO_ROOT_USER: minioadmin
    MINIO_ROOT_PASSWORD: minioadmin
  ports:
    - "9000:9000"
    - "9001:9001"
  volumes:
    - minio_data:/data
```

Engine container gets env vars: `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`,
`MINIO_BUCKET`, `MINIO_SECURE`.

---

## Data Flow

1. `POST /crawl` creates a job and starts a background task (unchanged).
2. Job completes → `run_job()` in `service.py` injects `job_id` into payload meta → uploads to MinIO as `crawl-{job_id}.json`.
3. User calls `POST /query` with filters → DuckDB reads `crawl-*.json` from MinIO via httpfs → returns `CrawlSummary` list.
4. User calls `GET /storage/{job_id}` → engine fetches file from MinIO → streams bytes back.

---

## Error Handling

- Upload failure: logged as warning, job marked `done` regardless. Result still available in memory within TTL.
- Query failure (DuckDB / httpfs): returns `500` with error detail.
- MinIO unreachable at startup: storage silently disabled; `/query` and `/storage/*` return `503`.
- Empty bucket: query returns empty list.

---

## Testing

- `tests/engine/test_storage.py` — unit tests for `put_result` / `get_result` using a mock MinIO client (no live MinIO required); verify `job_id` is injected into `meta`.
- `tests/engine/test_query.py` — unit tests for `CrawlQuery` → SQL translation using DuckDB against local fixture JSON files (no MinIO required; DuckDB reads local paths with the same `read_json` call).
- `tests/engine/test_service.py` — add cases for `/query` (returns 503 when storage disabled, returns results when storage mock returns fixture data) and `/storage/{job_id}`.

---

## Dependencies

- `minio` — MinIO Python SDK (sync; wrapped in `asyncio.to_thread`)
- `duckdb` — in-process analytical queries with `httpfs` extension

Both added to `pyproject.toml`.
