# One-Shot Natural Language Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user supply one natural-language string describing a whole crawl (CLI `--prompt` or HTTP `CrawlRequest.prompt`), parsed by a Haiku call into the same structured fields the explicit flags already produce.

**Architecture:** A new `engine/prompt_parser.py` module (`parse_crawl_prompt()`) renders a Jinja2 template, calls Haiku, parses/validates the JSON response, and returns a dict containing only the fields the prompt gave evidence for. The CLI and the HTTP API each call it, then merge: any explicitly-supplied field always wins over a parsed one, which wins over the existing hardcoded default.

**Tech Stack:** Python 3.12, `anthropic` (AsyncAnthropic), `jsonschema`, `pydantic` v2, Jinja2, FastAPI, `pytest` + `pytest-asyncio`.

## Global Constraints

- Explicit structured arguments (CLI flags actually passed / HTTP JSON keys actually present) always override anything the prompt parser extracted.
- An unusable prompt (no `seed_url` found, malformed JSON, schema-invalid response) always aborts before any crawl starts — never falls back to a guessed or empty `seed_url`.
- `extract_schema`, `token_budget`, `css_selector`, `max_chars` are not parsed from natural language; they stay explicit-only.
- No caching of parsed prompts.
- Model is the existing Haiku constant (`"claude-haiku-4-5-20251001"`), following the same local-constant convention as `engine/extractor.py`.
- Ruff: line-length 100, rules E/F/I/UP/B/SIM. All public functions get type hints; use `X | Y` not `Optional[X]`. All I/O is async (`AsyncAnthropic`, never the sync client).

Spec: `docs/superpowers/specs/2026-06-17-one-shot-nl-prompt-design.md`

---

### Task 1: `engine/prompt_parser.py` — `parse_crawl_prompt()`

**Files:**
- Create: `src/crawl_tool/engine/prompt_parser.py`
- Create: `src/crawl_tool/engine/prompts/parse_prompt.j2`
- Test: `tests/engine/test_prompt_parser.py`

**Interfaces:**
- Produces: `class PromptParseError(Exception)`; `async def parse_crawl_prompt(prompt: str, client: anthropic.AsyncAnthropic | None = None) -> dict`. Returned dict may contain only these keys: `seed_url, goal, extract_prompt, max_depth, max_pages, date_filter, include_undated, same_domain, include_patterns, exclude_patterns`. Raises `PromptParseError` if no valid `seed_url` is found, or the response isn't valid JSON matching the expected shape.
- Consumes: `crawl_tool.engine.prompts.render` (existing — `render(template_name: str, **context) -> str`).

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_prompt_parser.py`:

```python
"""Tests for src/prompt_parser.py — parse_crawl_prompt."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from crawl_tool.engine.prompt_parser import PromptParseError, parse_crawl_prompt


def _mock_response(text: str, stop_reason: str = "end_turn") -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.stop_reason = stop_reason
    return msg


@pytest.mark.asyncio
async def test_parse_crawl_prompt_returns_all_specified_fields():
    data = {
        "seed_url": "https://vnexpress.net",
        "goal": "collect tech news",
        "max_pages": 50,
    }
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(data)))
        result = await parse_crawl_prompt("crawl vnexpress.net for tech news, max 50 pages")
    assert result == data


@pytest.mark.asyncio
async def test_parse_crawl_prompt_strips_markdown_fences():
    data = {"seed_url": "https://vnexpress.net"}
    fenced = f"```json\n{json.dumps(data)}\n```"
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(fenced))
        result = await parse_crawl_prompt("crawl vnexpress.net")
    assert result == data


@pytest.mark.asyncio
async def test_parse_crawl_prompt_returns_only_specified_keys():
    data = {"seed_url": "https://vnexpress.net", "goal": "tech news"}
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(data)))
        result = await parse_crawl_prompt("crawl vnexpress.net for tech news")
    assert set(result.keys()) == {"seed_url", "goal"}


@pytest.mark.asyncio
async def test_parse_crawl_prompt_rejects_schemeless_url():
    data = {"seed_url": "vnexpress.net"}
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(data)))
        with pytest.raises(PromptParseError):
            await parse_crawl_prompt("crawl vnexpress.net")


@pytest.mark.asyncio
async def test_parse_crawl_prompt_missing_seed_url_raises():
    data = {"goal": "tech news"}
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(data)))
        with pytest.raises(PromptParseError):
            await parse_crawl_prompt("collect tech news")


@pytest.mark.asyncio
async def test_parse_crawl_prompt_invalid_json_raises():
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response("not valid json"))
        with pytest.raises(PromptParseError):
            await parse_crawl_prompt("crawl vnexpress.net")


@pytest.mark.asyncio
async def test_parse_crawl_prompt_schema_violation_raises():
    data = {"seed_url": "https://vnexpress.net", "max_pages": "fifty"}
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(data)))
        with pytest.raises(PromptParseError):
            await parse_crawl_prompt("crawl vnexpress.net, fifty pages")


@pytest.mark.asyncio
async def test_parse_crawl_prompt_rejects_max_depth_above_ceiling():
    data = {"seed_url": "https://vnexpress.net", "max_depth": 10}
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(data)))
        with pytest.raises(PromptParseError):
            await parse_crawl_prompt("crawl vnexpress.net 10 levels deep")


@pytest.mark.asyncio
async def test_parse_crawl_prompt_truncated_response_raises():
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response("{}", stop_reason="max_tokens")
        )
        with pytest.raises(PromptParseError):
            await parse_crawl_prompt("crawl vnexpress.net")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/engine/test_prompt_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'crawl_tool.engine.prompt_parser'`

Note: `test_parse_crawl_prompt_rejects_max_depth_above_ceiling` exists so the HTTP API and the CLI reject an out-of-range `max_depth` the same way — as a `PromptParseError`/400 before any job starts, not as an unvalidated `setattr` that only fails later inside `AgentConfig` construction during job execution.

- [ ] **Step 3: Create the prompt template**

Create `src/crawl_tool/engine/prompts/parse_prompt.j2`:

```jinja
Parse the following natural-language crawl request into structured fields.

## Request
{{ prompt }}

## Fields
Include a key ONLY if the request gives clear evidence for it. Do not guess or invent a default for any field.

- "seed_url": the URL to start crawling. Always include the scheme (e.g. add "https://" if the user gave a bare domain like "vnexpress.net").
- "goal": a short natural-language description of what the crawl is trying to accomplish.
- "extract_prompt": what structured data to pull out of each page.
- "max_depth": integer link-following depth from the seed URL.
- "max_pages": integer maximum number of pages to fetch.
- "date_filter": a natural-language date range fragment (e.g. "last 7 days"). Do not resolve it to actual calendar dates yourself.
- "include_undated": boolean — true if pages with no detectable publish date should still be included.
- "same_domain": boolean — true if the crawl should stay on the seed URL's domain.
- "include_patterns": array of URL glob patterns to include.
- "exclude_patterns": array of URL glob patterns to exclude.

Respond with a single JSON object containing only the keys you found evidence for — no markdown code fences, no explanation, no extra keys.
```

- [ ] **Step 4: Write the implementation**

Create `src/crawl_tool/engine/prompt_parser.py`:

```python
"""Parse a one-shot natural-language crawl description into structured fields."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import anthropic
import jsonschema
import structlog

from crawl_tool.engine.config import MAX_DEPTH_CEILING
from crawl_tool.engine.prompts import render

logger = structlog.get_logger(__name__)

MODEL = "claude-haiku-4-5-20251001"

_PARSED_PROMPT_SCHEMA = {
    "type": "object",
    "properties": {
        "seed_url": {"type": "string"},
        "goal": {"type": "string"},
        "extract_prompt": {"type": "string"},
        "max_depth": {"type": "integer", "minimum": 0, "maximum": MAX_DEPTH_CEILING},
        "max_pages": {"type": "integer"},
        "date_filter": {"type": "string"},
        "include_undated": {"type": "boolean"},
        "same_domain": {"type": "boolean"},
        "include_patterns": {"type": "array", "items": {"type": "string"}},
        "exclude_patterns": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


class PromptParseError(Exception):
    """Raised when a one-shot prompt cannot be parsed into a usable seed_url."""


def _strip_fences(text: str) -> str:
    """Strip markdown code fences Claude sometimes adds despite instructions."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    return match.group(1).strip() if match else text


async def parse_crawl_prompt(
    prompt: str, client: anthropic.AsyncAnthropic | None = None
) -> dict:
    """Parse a one-shot natural-language crawl description into structured fields.

    Args:
        prompt: Natural-language description of the whole crawl.
        client: Shared Anthropic client; a new one is created if not provided.

    Returns:
        A dict containing only the keys the prompt gave evidence for. Possible keys:
        seed_url, goal, extract_prompt, max_depth, max_pages, date_filter,
        include_undated, same_domain, include_patterns, exclude_patterns.

    Raises:
        PromptParseError: no usable seed_url was found, or the response could not
            be parsed as valid JSON matching the expected shape.
    """
    client = client or anthropic.AsyncAnthropic()
    user_content = render("parse_prompt.j2", prompt=prompt)

    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": user_content}],
    )

    if not response.content or response.stop_reason == "max_tokens":
        logger.warning(
            "parse_crawl_prompt: truncated response", stop_reason=response.stop_reason
        )
        raise PromptParseError("empty or truncated response from Claude")

    raw = _strip_fences(response.content[0].text)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("parse_crawl_prompt: JSON parse error", exc=str(exc))
        raise PromptParseError(f"JSON parse error: {exc}") from exc

    try:
        jsonschema.validate(instance=parsed, schema=_PARSED_PROMPT_SCHEMA)
    except jsonschema.ValidationError as exc:
        logger.warning("parse_crawl_prompt: schema validation failed", error=exc.message)
        raise PromptParseError(f"schema validation failed: {exc.message}") from exc

    seed_url = parsed.get("seed_url")
    if not seed_url:
        raise PromptParseError("no seed url found in prompt")
    url_parts = urlparse(seed_url)
    if not url_parts.scheme or not url_parts.netloc:
        raise PromptParseError(f"seed url is not a valid absolute URL: {seed_url!r}")

    logger.debug("parse_crawl_prompt done", fields=list(parsed.keys()))
    return parsed
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/engine/test_prompt_parser.py -v`
Expected: PASS (9 tests)

- [ ] **Step 6: Lint**

Run: `uv run ruff check src/crawl_tool/engine/prompt_parser.py tests/engine/test_prompt_parser.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/crawl_tool/engine/prompt_parser.py src/crawl_tool/engine/prompts/parse_prompt.j2 tests/engine/test_prompt_parser.py
git commit -m "feat: add parse_crawl_prompt for one-shot natural language crawl descriptions"
```

---

### Task 2: `engine/contract.py` — accept `prompt` on `CrawlRequest`

**Files:**
- Modify: `src/crawl_tool/engine/contract.py`
- Test: `tests/engine/test_contract.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `CrawlRequest.seed_url: str = ""` (was required, no default), `CrawlRequest.prompt: str | None = None` (new field). Model raises `pydantic.ValidationError` at construction if both `seed_url` and `prompt` are empty/`None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/engine/test_contract.py` (after the existing imports, no import changes needed):

```python
def test_crawl_request_allows_prompt_only():
    request = CrawlRequest(prompt="crawl vnexpress.net for tech news")
    assert request.seed_url == ""
    assert request.prompt == "crawl vnexpress.net for tech news"


def test_crawl_request_requires_seed_url_or_prompt():
    with pytest.raises(ValidationError):
        CrawlRequest()
```

(The existing `test_crawl_request_requires_seed_url` test already covers `CrawlRequest()` raising — keep it as-is; the new test above is the same assertion under the new, more accurate name. Leave both in the file.)

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `uv run python -m pytest tests/engine/test_contract.py -v`
Expected: `test_crawl_request_allows_prompt_only` FAILS with a `ValidationError` (because `seed_url` is currently a required field with no default), all other tests still PASS.

- [ ] **Step 3: Write the implementation**

In `src/crawl_tool/engine/contract.py`, change the import line and the `CrawlRequest` class:

```python
from pydantic import BaseModel, Field, model_validator
```

```python
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
    def _require_seed_url_or_prompt(self) -> CrawlRequest:
        if not self.seed_url and not self.prompt:
            raise ValueError("either seed_url or prompt must be provided")
        return self

    def to_agent_config(self) -> AgentConfig:
        ...  # unchanged
```

(`to_agent_config()` body is unchanged — it never references `prompt`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/engine/test_contract.py -v`
Expected: PASS (all tests, including the two new ones)

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `uv run python -m pytest`
Expected: PASS — no other test constructs `CrawlRequest` without a `seed_url`, so the relaxed field shouldn't break anything else.

- [ ] **Step 6: Lint**

Run: `uv run ruff check src/crawl_tool/engine/contract.py tests/engine/test_contract.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/crawl_tool/engine/contract.py tests/engine/test_contract.py
git commit -m "feat: accept optional prompt field on CrawlRequest"
```

---

### Task 3: `engine/service.py` — resolve `prompt` in `POST /crawl`

**Files:**
- Modify: `src/crawl_tool/engine/service.py`
- Test: `tests/engine/test_service.py`

**Interfaces:**
- Consumes: `parse_crawl_prompt(prompt: str) -> dict` and `PromptParseError` from Task 1; `CrawlRequest.prompt` and `CrawlRequest.model_fields_set` from Task 2.
- Produces: `POST /crawl` now resolves `request.prompt` (if set) into the request's fields before creating the job; raises `HTTPException(400, ...)` if the prompt can't be parsed or yields no `seed_url`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/engine/test_service.py`. Add this import alongside the existing ones:

```python
from crawl_tool.engine.prompt_parser import PromptParseError
```

Add these tests:

```python
@pytest.mark.asyncio
async def test_crawl_with_prompt_only_uses_parsed_seed_url():
    app = create_app()
    parsed = {"seed_url": "https://parsed.example"}
    with (
        patch("crawl_tool.engine.service.parse_crawl_prompt", AsyncMock(return_value=parsed)),
        patch("crawl_tool.engine.service.execute", AsyncMock(return_value=_PAYLOAD)) as mock_execute,
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
        patch("crawl_tool.engine.service.execute", AsyncMock(return_value=_PAYLOAD)) as mock_execute,
    ):
        async with _client(app) as client:
            created = (
                await client.post(
                    "/crawl", json={"prompt": "crawl something", "max_pages": 20}
                )
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/engine/test_service.py -v`
Expected: FAIL — the new tests' `patch("crawl_tool.engine.service.parse_crawl_prompt", ...)` raises `AttributeError` because `service.py` doesn't import `parse_crawl_prompt` yet, and `test_crawl_prompt_with_no_seed_url_found_returns_400` / `test_crawl_prompt_parse_failure_returns_400` get a 200 instead of 400 since `request.prompt` is currently ignored.

- [ ] **Step 3: Write the implementation**

In `src/crawl_tool/engine/service.py`, add the import:

```python
from crawl_tool.engine.prompt_parser import PromptParseError, parse_crawl_prompt
```

Replace the `start_crawl` handler body:

```python
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
                    status_code=400, detail="no seed url provided or found in prompt"
                )
        purge_expired()
        job_id = uuid4().hex
        job = Job(request)
        jobs[job_id] = job
        job.task = asyncio.create_task(run_job(job_id))
        return JobCreated(job_id=job_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/engine/test_service.py -v`
Expected: PASS (all tests, including the 5 new ones)

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `uv run python -m pytest`
Expected: PASS

- [ ] **Step 6: Lint**

Run: `uv run ruff check src/crawl_tool/engine/service.py tests/engine/test_service.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/crawl_tool/engine/service.py tests/engine/test_service.py
git commit -m "feat: resolve prompt field into structured request in POST /crawl"
```

---

### Task 4: `engine/cli.py` — `--prompt` flag and merge logic

**Files:**
- Modify: `src/crawl_tool/engine/cli.py`
- Test: `tests/engine/test_main_build_parser.py`, `tests/engine/test_main_run.py`

**Interfaces:**
- Consumes: `parse_crawl_prompt`, `PromptParseError` from Task 1.
- Produces: `build_parser()` adds `--prompt` (default `""`); `url` positional becomes optional (`nargs="?"`, default `None`); `--goal`, `--extract-prompt`, `--max-depth`, `--max-pages`, `--date-filter`, `--include-undated`, `--same-domain`, `--include-pattern`, `--exclude-pattern` default to `None` instead of their previous concrete defaults, so `run()` can tell "not passed" apart from "passed". `run()` resolves the final values via a `pick()` helper before constructing `CrawlRequest`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/engine/test_main_build_parser.py`:

```python
def test_build_parser_url_is_optional_when_prompt_used():
    args = build_parser().parse_args(["--prompt", "crawl vnexpress.net"])
    assert args.url is None
    assert args.prompt == "crawl vnexpress.net"


def test_build_parser_override_flags_default_to_none():
    args = build_parser().parse_args(["https://cafef.vn"])
    assert args.goal is None
    assert args.extract_prompt is None
    assert args.max_depth is None
    assert args.max_pages is None
    assert args.date_filter is None
    assert args.include_undated is None
    assert args.same_domain is None
    assert args.include_pattern is None
    assert args.exclude_pattern is None
```

Add to `tests/engine/test_main_run.py`. Add this import alongside the existing ones:

```python
from crawl_tool.engine.prompt_parser import PromptParseError
```

Add these tests:

```python
@pytest.mark.asyncio
async def test_run_uses_prompt_when_no_url_given(tmp_path):
    out = tmp_path / "out.json"
    args = build_parser().parse_args([
        "--prompt", "crawl vnexpress.net for tech news",
        "--output", str(out),
    ])
    parsed = {"seed_url": "https://vnexpress.net", "goal": "tech news"}
    payload = {"meta": {"total_pages": 0}, "pages": []}
    with (
        patch("crawl_tool.engine.cli.configure_logging"),
        patch("crawl_tool.engine.cli.parse_crawl_prompt", AsyncMock(return_value=parsed)),
        patch("crawl_tool.engine.cli.execute", AsyncMock(return_value=payload)) as mock_execute,
    ):
        await run(args)
    request = mock_execute.call_args.args[0]
    assert request.seed_url == "https://vnexpress.net"
    assert request.goal == "tech news"


@pytest.mark.asyncio
async def test_run_explicit_flag_overrides_prompt(tmp_path):
    out = tmp_path / "out.json"
    args = build_parser().parse_args([
        "--prompt", "crawl vnexpress.net, max 50 pages",
        "--max-pages", "20",
        "--output", str(out),
    ])
    parsed = {"seed_url": "https://vnexpress.net", "max_pages": 50}
    payload = {"meta": {"total_pages": 0}, "pages": []}
    with (
        patch("crawl_tool.engine.cli.configure_logging"),
        patch("crawl_tool.engine.cli.parse_crawl_prompt", AsyncMock(return_value=parsed)),
        patch("crawl_tool.engine.cli.execute", AsyncMock(return_value=payload)) as mock_execute,
    ):
        await run(args)
    request = mock_execute.call_args.args[0]
    assert request.max_pages == 20


@pytest.mark.asyncio
async def test_run_positional_url_overrides_prompt_seed_url(tmp_path):
    out = tmp_path / "out.json"
    args = build_parser().parse_args([
        "https://explicit.example",
        "--prompt", "crawl vnexpress.net",
        "--output", str(out),
    ])
    parsed = {"seed_url": "https://vnexpress.net"}
    payload = {"meta": {"total_pages": 0}, "pages": []}
    with (
        patch("crawl_tool.engine.cli.configure_logging"),
        patch("crawl_tool.engine.cli.parse_crawl_prompt", AsyncMock(return_value=parsed)),
        patch("crawl_tool.engine.cli.execute", AsyncMock(return_value=payload)) as mock_execute,
    ):
        await run(args)
    request = mock_execute.call_args.args[0]
    assert request.seed_url == "https://explicit.example"


@pytest.mark.asyncio
async def test_run_no_url_and_no_prompt_skips_agent():
    args = build_parser().parse_args([])
    with (
        patch("crawl_tool.engine.cli.configure_logging"),
        patch("crawl_tool.engine.cli.execute", AsyncMock()) as mock_execute,
    ):
        await run(args)
    mock_execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_prompt_parse_failure_skips_agent():
    args = build_parser().parse_args(["--prompt", "???"])
    with (
        patch("crawl_tool.engine.cli.configure_logging"),
        patch(
            "crawl_tool.engine.cli.parse_crawl_prompt",
            AsyncMock(side_effect=PromptParseError("boom")),
        ),
        patch("crawl_tool.engine.cli.execute", AsyncMock()) as mock_execute,
    ):
        await run(args)
    mock_execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_without_include_undated_flag_defaults_false(tmp_path):
    out = tmp_path / "out.json"
    args = build_parser().parse_args(["https://cafef.vn", "--output", str(out)])
    payload = {"meta": {"total_pages": 0}, "pages": []}
    with (
        patch("crawl_tool.engine.cli.configure_logging"),
        patch("crawl_tool.engine.cli.execute", AsyncMock(return_value=payload)) as mock_execute,
    ):
        await run(args)
    request = mock_execute.call_args.args[0]
    assert request.include_undated is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/engine/test_main_build_parser.py tests/engine/test_main_run.py -v`
Expected: FAIL — `build_parser` tests fail because `url` is still required and override flags still have concrete defaults; `run` tests fail because `--prompt` isn't a recognized flag yet.

- [ ] **Step 3: Write the implementation**

In `src/crawl_tool/engine/cli.py`, add the import:

```python
from crawl_tool.engine.prompt_parser import PromptParseError, parse_crawl_prompt
```

Replace `build_parser()`:

```python
def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Returns:
        Configured argparse parser for the crawl-tool CLI.
    """
    parser = argparse.ArgumentParser(
        prog="crawl-tool",
        description="Agent-driven LLM crawler with structured extraction.",
    )
    parser.add_argument("url", nargs="?", default=None, help="Seed URL to crawl")
    parser.add_argument(
        "--prompt",
        default="",
        help="One-shot natural-language crawl description; fills in any field not given explicitly",
    )
    parser.add_argument("--goal", default=None, help="Natural-language crawl goal")
    parser.add_argument("--extract-prompt", default=None, help="What to extract from each page")
    parser.add_argument("--extract-schema", default="", help="Path to JSON Schema file")
    parser.add_argument("--max-depth", type=int, default=None, help=f"Maximum crawl depth (default: 1, ceiling: {MAX_DEPTH_CEILING})")
    parser.add_argument("--max-pages", type=int, default=None, help="Maximum pages to crawl (default: 100)")
    parser.add_argument("--token-budget", type=int, default=500_000, help="Total token budget (default: 500000)")
    parser.add_argument("--date-filter", default=None, help="Natural-language date filter, e.g. 'last 7 days'")
    parser.add_argument("--include-undated", action=argparse.BooleanOptionalAction, default=None, help="Include pages with no detectable date")
    parser.add_argument("--css-selector", default="", help="CSS selector to restrict page content extraction")
    parser.add_argument("--max-chars", type=int, default=0, help="Truncate page markdown to this many chars before sending to Claude (0 = no limit)")
    parser.add_argument("--same-domain", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--include-pattern", action="append", default=None, metavar="PATTERN")
    parser.add_argument("--exclude-pattern", action="append", default=None, metavar="PATTERN")
    parser.add_argument("--output", default="output.json", help="Output file path (default: output.json)")
    parser.add_argument("--format", choices=["json", "jsonl"], default="json")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser
```

Replace `run()`:

```python
async def run(args: argparse.Namespace) -> None:
    """Run the crawler from parsed command-line arguments.

    Args:
        args: Parsed CLI arguments from build_parser.
    """
    configure_logging(args.verbose)

    parsed: dict = {}
    if args.prompt:
        try:
            parsed = await parse_crawl_prompt(args.prompt)
        except PromptParseError as exc:
            logger.error("could not parse prompt", error=str(exc))
            return

    seed_url = args.url or parsed.get("seed_url")
    if not seed_url:
        logger.error("no seed url provided (pass a url, or include one in --prompt)")
        return

    def pick(arg_name: str, parsed_name: str, fallback):
        explicit = getattr(args, arg_name)
        return explicit if explicit is not None else parsed.get(parsed_name, fallback)

    goal = pick("goal", "goal", "")
    extract_prompt = pick("extract_prompt", "extract_prompt", "")
    max_depth = pick("max_depth", "max_depth", 1)
    max_pages = pick("max_pages", "max_pages", 100)
    date_filter = pick("date_filter", "date_filter", "")
    include_undated = pick("include_undated", "include_undated", False)
    same_domain = pick("same_domain", "same_domain", True)
    include_patterns = pick("include_pattern", "include_patterns", [])
    exclude_patterns = pick("exclude_pattern", "exclude_patterns", [])

    if not 0 <= max_depth <= MAX_DEPTH_CEILING:
        logger.error(
            "max-depth out of range", max_depth=max_depth, ceiling=MAX_DEPTH_CEILING
        )
        return

    extract_schema = None
    if args.extract_schema:
        schema_path = Path(args.extract_schema)
        if not await asyncio.to_thread(schema_path.exists):
            logger.error("extract schema file not found", path=args.extract_schema)
            return
        schema_text = await asyncio.to_thread(schema_path.read_text, encoding="utf-8")
        extract_schema = json.loads(schema_text)

    request = CrawlRequest(
        seed_url=seed_url,
        goal=goal,
        extract_prompt=extract_prompt,
        extract_schema=extract_schema,
        max_depth=max_depth,
        max_pages=max_pages,
        token_budget=args.token_budget,
        same_domain=same_domain,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        date_filter=date_filter,
        include_undated=include_undated,
        css_selector=args.css_selector,
        max_chars=args.max_chars,
    )

    logger.info(
        "running crawl",
        seed_url=seed_url,
        goal=goal or None,
    )
    payload = await execute(request, CrawlState())

    fmt = args.format
    await asyncio.to_thread(
        Path(args.output).write_text,
        serialize_payload(payload, fmt),
        encoding="utf-8",
    )
    logger.info(
        "crawl done",
        pages=payload["meta"]["total_pages"],
        output=args.output,
    )
```

(`main()` is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/engine/test_main_build_parser.py tests/engine/test_main_run.py -v`
Expected: PASS (all tests, including the new ones)

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `uv run python -m pytest`
Expected: PASS — every existing CLI test passes explicit flags, so the `None`-sentinel default change is invisible to them; only the new "no flag passed" tests exercise the new fallback path.

- [ ] **Step 6: Lint and format**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/crawl_tool/engine/cli.py tests/engine/test_main_build_parser.py tests/engine/test_main_run.py
git commit -m "feat: add --prompt flag for one-shot natural language crawl configuration"
```

---

## Manual Verification (after Task 4)

```bash
ANTHROPIC_API_KEY=... uv run crawl-tool --prompt "Crawl vnexpress.net for tech news from the last 7 days, max 10 pages" --output /tmp/out.json --verbose
```

Confirm in the log output that `seed_url` resolves to a `vnexpress.net` URL and the crawl proceeds; confirm passing an unrelated `--max-pages 3` alongside `--prompt` produces a request capped at 3 pages even if the prompt said 10.
