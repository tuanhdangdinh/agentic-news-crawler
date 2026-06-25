"""HTTP API request/response models. These drive the OpenAPI schema."""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import BaseModel, Field, model_validator

from crawl_tool.engine.config import MAX_DEPTH_CEILING, AgentConfig


class CrawlRequest(BaseModel):
    """A crawl request: seed URL plus the user-facing crawl parameters."""

    seed_url: str = ""
    prompt: str | None = None
    goal: str = ""
    extract_prompt: str = ""
    extract_schema: dict | None = None
    max_depth: int = Field(default=1, ge=0, le=MAX_DEPTH_CEILING)
    max_pages: int = 100
    token_budget: int = 500_000
    same_domain: bool = True
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    date_filter: str = ""
    include_undated: bool = True
    css_selector: str = ""
    max_chars: int = 0

    @model_validator(mode="after")
    def _require_seed_url_or_prompt(self) -> Self:
        if not self.seed_url and not self.prompt:
            raise ValueError("either seed_url or prompt must be provided")
        return self

    def to_agent_config(self) -> AgentConfig:
        """Build the internal crawl configuration.

        Returns:
            Agent configuration populated from the request fields.
        """
        return AgentConfig(
            goal=self.goal,
            extract_prompt=self.extract_prompt,
            extract_schema=self.extract_schema,
            max_depth=self.max_depth,
            max_pages=self.max_pages,
            token_budget=self.token_budget,
            same_domain=self.same_domain,
            include_patterns=self.include_patterns,
            exclude_patterns=self.exclude_patterns,
            date_filter=self.date_filter,
            include_undated=self.include_undated,
            css_selector=self.css_selector,
            max_chars=self.max_chars,
        )


class JobStatus(str, Enum):  # noqa: UP042
    """Lifecycle states of a crawl job."""

    queued = "queued"
    running = "running"
    done = "done"
    error = "error"


class JobProgress(BaseModel):
    """Coarse progress signal while a crawl runs."""

    pages_collected: int = 0


class JobCreated(BaseModel):
    """Response to POST /crawl."""

    job_id: str


class JobResult(BaseModel):
    """Response to GET /crawl/{job_id}."""

    status: JobStatus
    progress: JobProgress = Field(default_factory=JobProgress)
    payload: dict | None = None
    error: str | None = None


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
