"""User-supplied crawl configuration and hard limits."""

from __future__ import annotations

from pydantic import BaseModel, Field

MODEL = "claude-haiku-4-5-20251001"
MAX_DEPTH_CEILING = 5


class AgentConfig(BaseModel):
    """User-supplied parameters for a crawl run."""

    goal: str = ""
    max_depth: int = Field(default=1, ge=0, le=MAX_DEPTH_CEILING)
    max_pages: int = 100
    token_budget: int = 500_000
    same_domain: bool = True
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    model: str = MODEL
    extract_prompt: str = ""
    extract_schema: dict | None = None
    extract_schema_inferred: bool = False
    date_filter: str = ""
    include_undated: bool = True
    css_selector: str = ""
    max_chars: int = 0
