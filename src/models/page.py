"""Shared domain model for a fetched page."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PageResult(BaseModel):
    """Normalised output of a single page fetch."""

    url: str
    final_url: str
    status_code: int | None
    title: str | None
    markdown: str
    raw_markdown: str | None = None
    html: str | None = None
    links_internal: list[str] = Field(default_factory=list)
    links_external: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    fetch_time: float | None = None
    headers: dict = Field(default_factory=dict)
    success: bool = True
    error: str | None = None
