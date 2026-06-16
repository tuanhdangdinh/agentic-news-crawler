"""HTTP API request/response models. These drive the OpenAPI schema."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from crawl_tool.engine.config import MAX_DEPTH_CEILING, AgentConfig


class CrawlRequest(BaseModel):
    """A crawl request: seed URL plus the user-facing crawl parameters."""

    seed_url: str
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
