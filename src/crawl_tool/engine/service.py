"""FastAPI service exposing the crawl engine as polled async jobs."""

from __future__ import annotations

import asyncio
import os
from time import monotonic as _monotonic
from uuid import uuid4

import structlog
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from crawl_tool.engine.agent import CrawlState
from crawl_tool.engine.contract import (
    CrawlQuery,
    CrawlRequest,
    CrawlSummary,
    JobCreated,
    JobProgress,
    JobResult,
    JobStatus,
)
from crawl_tool.engine.output import serialize_payload
from crawl_tool.engine.prompt_parser import PromptParseError, parse_crawl_prompt
from crawl_tool.engine.query import run_query
from crawl_tool.engine.runner import execute
from crawl_tool.engine.storage import StorageSettings, get_result, put_result

logger = structlog.get_logger(__name__)

JOB_TTL_SECONDS = 3600


class Job:
    """One crawl job and its mutable execution state.

    Attributes:
        request: Validated request submitted for execution.
        state: Mutable crawl state used for live progress.
        status: Current job lifecycle status.
        payload: Completed result payload when available.
        error: Captured execution error when available.
        created_at: Monotonic creation timestamp used for expiry.
        task: Background task running the crawl.
    """

    def __init__(self, request: CrawlRequest) -> None:
        self.request = request
        self.state = CrawlState()
        self.status = JobStatus.queued
        self.payload: dict | None = None
        self.error: str | None = None
        self.created_at = _monotonic()
        self.task: asyncio.Task[None] | None = None

    def to_result(self) -> JobResult:
        """Build the current API representation of the job.

        Returns:
            Job result containing status, live progress, payload, and error.
        """
        return JobResult(
            status=self.status,
            progress=JobProgress(pages_collected=len(self.state.pages)),
            payload=self.payload,
            error=self.error,
        )


def create_app() -> FastAPI:
    """Build a FastAPI application with an isolated job registry and run lock.

    Returns:
        FastAPI application exposing crawl job endpoints.
    """
    app = FastAPI(title="crawl-engine", version="0.1.0")

    origins = [origin for origin in os.environ.get("CORS_ALLOW_ORIGINS", "*").split(",") if origin]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    jobs: dict[str, Job] = {}
    run_lock = asyncio.Lock()
    storage_settings = StorageSettings.from_env()

    def purge_expired() -> None:
        cutoff = _monotonic() - JOB_TTL_SECONDS
        for job_id in [
            job_id
            for job_id, job in jobs.items()
            if job.status in (JobStatus.done, JobStatus.error) and job.created_at < cutoff
        ]:
            del jobs[job_id]

    async def run_job(job_id: str) -> None:
        job = jobs[job_id]
        async with run_lock:
            job.status = JobStatus.running
            try:
                job.payload = await execute(job.request, job.state)
                job.status = JobStatus.done
                if storage_settings.enabled:
                    try:
                        await put_result(job_id, job.payload, storage_settings)
                    except Exception as upload_exc:  # noqa: BLE001
                        logger.warning("storage upload failed", job_id=job_id, error=str(upload_exc))
            except Exception as exc:  # noqa: BLE001
                job.error = str(exc)
                job.status = JobStatus.error
                logger.warning("crawl job failed", job_id=job_id, error=str(exc))

    @app.get("/healthz")
    async def healthz() -> dict:
        """Return a basic process health response.

        Returns:
            Static health status payload.
        """
        return {"status": "ok"}

    @app.post("/crawl")
    async def start_crawl(request: CrawlRequest) -> JobCreated:
        """Create a queued crawl job and start its background task.

        Args:
            request: Validated crawl request.

        Returns:
            Identifier for the created job.
        """
        if request.prompt:
            try:
                parsed = await parse_crawl_prompt(request.prompt)
            except PromptParseError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            for field, value in parsed.items():
                if field not in request.model_fields_set:
                    setattr(request, field, value)
            if not request.seed_url:
                raise HTTPException(
                    status_code=400,
                    detail="no seed url provided or found in prompt",
                )
        purge_expired()
        job_id = uuid4().hex
        job = Job(request)
        jobs[job_id] = job
        job.task = asyncio.create_task(run_job(job_id))
        return JobCreated(job_id=job_id)

    @app.get("/crawl/{job_id}")
    async def get_crawl(job_id: str) -> JobResult:
        """Return the current state of a crawl job.

        Args:
            job_id: Identifier of the requested job.

        Returns:
            Current job status, progress, payload, and error.
        """
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job.to_result()

    @app.get("/crawl/{job_id}/result")
    async def get_crawl_result(job_id: str, format: str = "json") -> Response:
        """Download a completed crawl result as JSON or JSONL.

        Args:
            job_id: Identifier of the completed job.
            format: Requested serialization format.

        Returns:
            Serialized result attachment.
        """
        job = jobs.get(job_id)
        if job is None or job.status != JobStatus.done or job.payload is None:
            raise HTTPException(status_code=404, detail="result not available")
        fmt = "jsonl" if format == "jsonl" else "json"
        body = serialize_payload(job.payload, fmt)
        media_type = "application/x-ndjson" if fmt == "jsonl" else "application/json"
        filename = f"crawl-{job_id}.{fmt}"
        return Response(
            content=body,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

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

    return app


app = create_app()
