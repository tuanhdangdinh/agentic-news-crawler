# Engine / UI API Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the codebase into a self-contained OpenAPI-first crawl engine and a pure-HTTP Gradio reference client, each packageable as its own Docker image.

**Architecture:** A `uv` workspace with two members — `crawl_engine` (FastAPI service wrapping the existing crawl loop as async jobs) and `crawl_gradio` (Gradio UI that talks to the engine only over HTTP). The two packages share no Python code; their only contract is the HTTP API. Crawls run as serialized in-memory background jobs the UI polls.

**Tech Stack:** Python 3.11, uv workspace, FastAPI + uvicorn (engine), httpx + Gradio (UI), pytest/pytest-asyncio, Docker + docker-compose.

**Reference spec:** `docs/superpowers/specs/2026-06-12-engine-ui-api-split-design.md`

**Verification commands (run from repo root):**
- Tests: `uv run pytest -m "not integration" -q`
- Lint: `uv run ruff check .`

---

## File Structure (target)

```text
pyproject.toml                              # workspace root: members, ruff, pytest, dev group
docker-compose.yml
packages/
  engine/
    pyproject.toml
    Dockerfile
    conftest.py                             # moved from repo-root conftest.py
    src/crawl_engine/
      __init__.py
      models.py                             # PageResult (was src/models/page.py)
      config.py                             # AgentConfig, MAX_DEPTH_CEILING (lifted from agent.py)
      logging_config.py
      output.py                             # + serialize_payload()
      crawler.py
      agent.py                              # run_agent gains optional state param
      extractor.py
      schema_registry.py
      date_filter.py
      prompts.py
      prompts/*.j2
      runner.py                             # NEW — execute(request, state) -> payload
      contract.py                           # NEW — CrawlRequest, JobStatus, JobResult, ...
      service.py                            # NEW — FastAPI app + job registry
      cli.py                                # was main.py
    tests/                                  # all engine unit + integration tests
  gradio/
    pyproject.toml
    Dockerfile
    src/crawl_gradio/
      __init__.py
      app.py                                # was repo-root app.py
      ui.py                                 # run_crawl becomes a polling async generator
      ui_results.py
      client.py                             # NEW — httpx engine client
    tests/                                  # test_ui, test_ui_results, test_dev_ui, test_client
```

---

## Task 1: Restructure into a uv workspace (physical move, no logic change)

This task physically relocates every module and test into the two-package layout and rewrites imports. It changes no behavior — the suite must be green at the end. The Gradio package temporarily imports `crawl_engine` in-process; that coupling is removed in Task 10.

**Files:**
- Create: `pyproject.toml` (root, rewritten), `packages/engine/pyproject.toml`, `packages/gradio/pyproject.toml`
- Move: all of `src/*.py` and `src/models/` → `packages/engine/src/crawl_engine/`; `main.py` → `packages/engine/src/crawl_engine/cli.py`; `src/ui.py`, `src/ui_results.py` → `packages/gradio/src/crawl_gradio/`; `app.py`, `dev_ui.py` → `packages/gradio/src/crawl_gradio/`; `conftest.py` → `packages/engine/conftest.py`; tests split between the two packages

- [ ] **Step 1: Create the directory skeleton**

```bash
mkdir -p packages/engine/src/crawl_engine packages/engine/tests
mkdir -p packages/gradio/src/crawl_gradio packages/gradio/tests
touch packages/engine/src/crawl_engine/__init__.py packages/gradio/src/crawl_gradio/__init__.py
touch packages/engine/tests/__init__.py packages/gradio/tests/__init__.py
```

- [ ] **Step 2: Move engine library modules**

```bash
git mv src/agent.py src/crawler.py src/date_filter.py src/extractor.py \
       src/logging_config.py src/output.py src/prompts.py src/schema_registry.py \
       packages/engine/src/crawl_engine/
git mv src/models/page.py packages/engine/src/crawl_engine/models.py
git rm src/models/__init__.py
git mv prompts packages/engine/src/crawl_engine/prompts
git mv main.py packages/engine/src/crawl_engine/cli.py
rmdir src/models 2>/dev/null || true
```

- [ ] **Step 3: Move the Gradio modules**

```bash
git mv src/ui.py src/ui_results.py packages/gradio/src/crawl_gradio/
git mv app.py packages/gradio/src/crawl_gradio/app.py
git mv dev_ui.py packages/gradio/src/crawl_gradio/dev_ui.py
git rm src/__init__.py
rmdir src 2>/dev/null || true
```

- [ ] **Step 4: Move tests to their packages**

```bash
git mv tests/test_agent_execute_tool_extract.py tests/test_agent_execute_tool_finish.py \
       tests/test_agent_execute_tool_frontier.py tests/test_agent_execute_tool_mark_visited.py \
       tests/test_agent_helpers.py tests/test_agent_run_agent.py tests/test_crawler_fetch_page.py \
       tests/test_date_filter.py tests/test_extractor_extract.py tests/test_extractor_infer_schema.py \
       tests/test_logging_config.py tests/test_main_build_parser.py tests/test_main_run.py \
       tests/test_output_write_json.py tests/test_output_write_jsonl.py tests/test_output_write_results.py \
       tests/test_render.py tests/test_schema_registry.py tests/test_integration.py \
       packages/engine/tests/
git mv tests/test_ui.py tests/test_ui_results.py tests/test_dev_ui.py packages/gradio/tests/
git mv conftest.py packages/engine/conftest.py
git rm tests/__init__.py
rmdir tests 2>/dev/null || true
```

- [ ] **Step 5: Rewrite imports across all moved files**

Rewrite every `src.` reference to `crawl_engine.`, and the moved-module references (`src.ui`, `src.main`) appropriately. On macOS (BSD sed):

```bash
# Engine package + engine tests + gradio package: src.* -> crawl_engine.*
grep -rl 'src\.' packages/engine packages/gradio | while read -r f; do
  sed -i '' -e 's/from src\./from crawl_engine./g' -e 's/import src\./import crawl_engine./g' "$f"
done
# main.py was renamed to crawl_engine.cli: fix test imports
grep -rl 'from main import\|import main' packages/engine/tests | while read -r f; do
  sed -i '' -e 's/from main import/from crawl_engine.cli import/g' -e 's/^import main$/import crawl_engine.cli as main/g' "$f"
done
# gradio tests patch "src.ui.*" targets -> "crawl_gradio.ui.*"
grep -rl 'src\.ui\|src\.ui_results\|from src.ui' packages/gradio/tests | while read -r f; do
  sed -i '' -e 's/src\.ui_results/crawl_gradio.ui_results/g' -e 's/src\.ui/crawl_gradio.ui/g' "$f"
done
```

After the sed pass, the Gradio modules (`ui.py`) still contain `from crawl_engine.agent import ...` etc. — that is the intended temporary in-process coupling, removed in Task 10.

- [ ] **Step 6: Write the workspace root `pyproject.toml`**

Replace the entire contents of `pyproject.toml`:

```toml
[tool.uv.workspace]
members = ["packages/engine", "packages/gradio"]

[dependency-groups]
dev = [
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "pytest-httpx>=0.30.0",
    "ruff>=0.4.0",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
ignore = ["E501"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["packages/engine/tests", "packages/gradio/tests"]
markers = [
    "integration: end-to-end tests that hit real sites and the Claude API (deselect with '-m not integration')",
    "slow: tests that take more than a few seconds",
]
```

- [ ] **Step 7: Write `packages/engine/pyproject.toml`**

```toml
[project]
name = "crawl-engine"
version = "0.1.0"
description = "Agent-driven LLM crawl engine with an HTTP API"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "crawl4ai==0.8.6",
    "playwright>=1.44.0",
    "jinja2>=3.1.0",
    "jsonschema>=4.23.0",
    "python-dateutil>=2.9.0",
    "dateparser>=1.2.0",
    "beautifulsoup4>=4.12.0",
    "lxml>=5.0.0",
    "pydantic>=2.7.0",
    "rich>=13.7.0",
    "structlog>=24.0.0",
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.29.0",
]

[project.scripts]
crawl-tool = "crawl_engine.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/crawl_engine"]

[tool.hatch.build.targets.wheel.force-include]
"src/crawl_engine/prompts" = "crawl_engine/prompts"
```

- [ ] **Step 8: Write `packages/gradio/pyproject.toml`**

```toml
[project]
name = "crawl-gradio"
version = "0.1.0"
description = "Gradio reference client for the crawl engine"
requires-python = ">=3.11"
dependencies = [
    "gradio>=6.0.1,<7",
    "httpx>=0.27.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/crawl_gradio"]
```

- [ ] **Step 9: Confirm the prompts loader resolves templates from the package**

Open `packages/engine/src/crawl_engine/prompts.py`. It must locate templates relative to its own file (not the old repo-root `prompts/`). Confirm the Jinja loader path is `Path(__file__).parent / "prompts"`. If it points anywhere else (e.g. `Path.cwd()` or a repo-root path), change it to:

```python
from pathlib import Path
_TEMPLATE_DIR = Path(__file__).parent / "prompts"
```

and ensure the `FileSystemLoader` uses `_TEMPLATE_DIR`.

- [ ] **Step 10: Sync the workspace**

Run: `uv sync`
Expected: resolves both members editable plus the dev group, no errors.

- [ ] **Step 11: Run the full suite and lint**

Run: `uv run pytest -m "not integration" -q`
Expected: PASS — same count as before the move (232 passed at plan time).
Run: `uv run ruff check .`
Expected: `All checks passed!`

If `crawl_engine.cli` (former `main.py`) fails to import because it referenced `MAX_DEPTH_CEILING`/`AgentConfig` from `crawl_engine.agent`, that still works at this point (they remain in `agent.py` until Task 2). Do not change logic here.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "refactor: split repo into crawl_engine and crawl_gradio uv workspace"
```

---

## Task 2: Lift `AgentConfig` and `MAX_DEPTH_CEILING` into `config.py`

**Files:**
- Create: `packages/engine/src/crawl_engine/config.py`
- Modify: `packages/engine/src/crawl_engine/agent.py`
- Test: `packages/engine/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `packages/engine/tests/test_config.py`:

```python
"""Tests for crawl_engine.config."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crawl_engine.config import MAX_DEPTH_CEILING, AgentConfig


def test_default_max_depth_is_one():
    assert AgentConfig().max_depth == 1


def test_max_depth_ceiling_is_five():
    assert MAX_DEPTH_CEILING == 5
    assert AgentConfig(max_depth=5).max_depth == 5


def test_max_depth_above_ceiling_rejected():
    with pytest.raises(ValidationError):
        AgentConfig(max_depth=6)


def test_agent_module_reexports_config():
    from crawl_engine.agent import AgentConfig as AgentConfigViaAgent

    assert AgentConfigViaAgent is AgentConfig
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/engine/tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'crawl_engine.config'`

- [ ] **Step 3: Create `config.py` with the moved definitions**

Cut the `AgentConfig` class, the `MAX_DEPTH_CEILING` constant, and the `MODEL` default it depends on from `agent.py` and place them in a new `packages/engine/src/crawl_engine/config.py`:

```python
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
```

- [ ] **Step 4: Re-export from `agent.py` so existing imports keep working**

In `agent.py`, remove the moved `AgentConfig`/`MAX_DEPTH_CEILING`/`MODEL` definitions and add near the top imports:

```python
from crawl_engine.config import MAX_DEPTH_CEILING, MODEL, AgentConfig
```

Keep `CrawlState` in `agent.py`. Leave every other usage of `AgentConfig`/`MODEL` unchanged — they now resolve to the re-exported names.

- [ ] **Step 5: Point `cli.py` at the config module**

In `cli.py`, change `from crawl_engine.agent import MAX_DEPTH_CEILING, AgentConfig, run_agent` to:

```python
from crawl_engine.agent import run_agent
from crawl_engine.config import MAX_DEPTH_CEILING, AgentConfig
```

- [ ] **Step 6: Run tests and lint**

Run: `uv run pytest -m "not integration" -q`
Expected: PASS (now 236 with the four new config tests).
Run: `uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: move AgentConfig and depth ceiling into config.py"
```

---

## Task 3: Add `serialize_payload()` to `output.py`

**Files:**
- Modify: `packages/engine/src/crawl_engine/output.py`
- Test: `packages/engine/tests/test_output_serialize_payload.py`

- [ ] **Step 1: Write the failing test**

Create `packages/engine/tests/test_output_serialize_payload.py`:

```python
"""Tests for crawl_engine.output.serialize_payload."""

from __future__ import annotations

import json

from crawl_engine.output import serialize_payload

_PAYLOAD = {
    "meta": {"total_pages": 2},
    "pages": [{"url": "https://a", "title": "A"}, {"url": "https://b", "title": "B"}],
}


def test_serialize_json_round_trips_full_payload():
    text = serialize_payload(_PAYLOAD, "json")
    assert json.loads(text) == _PAYLOAD


def test_serialize_jsonl_is_one_object_per_page():
    text = serialize_payload(_PAYLOAD, "jsonl")
    lines = text.splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["url"] == "https://a"
    assert json.loads(lines[1])["url"] == "https://b"


def test_serialize_defaults_to_json():
    assert json.loads(serialize_payload(_PAYLOAD))["meta"]["total_pages"] == 2


def test_serialize_jsonl_handles_no_pages():
    assert serialize_payload({"meta": {}, "pages": []}, "jsonl") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/engine/tests/test_output_serialize_payload.py -q`
Expected: FAIL — `ImportError: cannot import name 'serialize_payload'`

- [ ] **Step 3: Implement `serialize_payload`**

Append to `output.py` (ensure `import json` is present at the top):

```python
def serialize_payload(payload: dict, fmt: str = "json") -> str:
    """Serialize a result payload to JSON or JSONL text.

    Args:
        payload: A result payload with "meta" and "pages" keys.
        fmt: "json" for the full payload, "jsonl" for one page object per line.

    Returns:
        The serialized payload as a string.
    """
    if fmt == "jsonl":
        return "\n".join(
            json.dumps(page, ensure_ascii=False) for page in payload.get("pages", [])
        )
    return json.dumps(payload, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/engine/tests/test_output_serialize_payload.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add serialize_payload for prebuilt result payloads"
```

---

## Task 4: Let `run_agent` accept an injected `CrawlState` (for live progress)

**Files:**
- Modify: `packages/engine/src/crawl_engine/agent.py`
- Test: `packages/engine/tests/test_agent_run_agent.py` (add one test)

- [ ] **Step 1: Write the failing test**

Append to `packages/engine/tests/test_agent_run_agent.py` (it already imports `AgentConfig`, `CrawlState`, `run_agent`, `_page`, `_finish_response`, `_end_turn_response`; reuse them):

```python
@pytest.mark.asyncio
async def test_run_agent_uses_injected_state():
    config = AgentConfig(goal="collect news", max_pages=1)
    injected = CrawlState()
    with (
        patch("crawl_engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_engine.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_end_turn_response())
        returned = await run_agent("https://cafef.vn", config, state=injected)
    assert returned is injected
    assert len(injected.pages) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/engine/tests/test_agent_run_agent.py::test_run_agent_uses_injected_state -q`
Expected: FAIL — `TypeError: run_agent() got an unexpected keyword argument 'state'`

- [ ] **Step 3: Add the optional parameter**

In `agent.py`, change the signature and the first state assignment:

```python
async def run_agent(
    seed_url: str, config: AgentConfig, state: CrawlState | None = None
) -> CrawlState:
```

Replace `state = CrawlState()` near the top of the body with:

```python
    state = state if state is not None else CrawlState()
```

Leave the rest of the function unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/engine/tests/test_agent_run_agent.py -q`
Expected: PASS (all existing run_agent tests plus the new one).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: allow run_agent to use an injected CrawlState"
```

---

## Task 5: Create `runner.py` — the request-to-payload execution seam

**Files:**
- Create: `packages/engine/src/crawl_engine/runner.py`
- Test: `packages/engine/tests/test_runner.py`

The payload helpers (`_page_record`, `_result_payload`, `_agent_run_meta`, `_direct_run_meta`) currently live in the Gradio `ui.py`. They move here; Task 10 deletes them from the UI.

- [ ] **Step 1: Write the failing test**

Create `packages/engine/tests/test_runner.py`:

```python
"""Tests for crawl_engine.runner."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from crawl_engine.agent import CrawlState
from crawl_engine.contract import CrawlRequest
from crawl_engine.models import PageResult
from crawl_engine.runner import execute


def _page(url: str = "https://cafef.vn", success: bool = True) -> PageResult:
    return PageResult(
        url=url,
        final_url=url,
        status_code=200 if success else 500,
        title="CafeF",
        markdown="Economy news",
        links_internal=[],
        success=success,
        error=None if success else "boom",
    )


@pytest.mark.asyncio
async def test_execute_direct_fetch_when_no_goal_or_extract():
    request = CrawlRequest(seed_url="https://cafef.vn")
    with patch("crawl_engine.runner.fetch_page", AsyncMock(return_value=_page())) as mock_fetch:
        payload = await execute(request, CrawlState())
    mock_fetch.assert_awaited_once()
    assert payload["meta"]["total_pages"] == 1
    assert payload["meta"]["finish_reason"] == "single page fetched"
    assert payload["pages"][0]["url"] == "https://cafef.vn"


@pytest.mark.asyncio
async def test_execute_runs_agent_and_fills_injected_state():
    request = CrawlRequest(seed_url="https://cafef.vn", goal="collect news")
    state = CrawlState()

    async def fake_run_agent(seed, config, state):
        state.pages.append(_page())
        state.finish_reason = "done"
        return state

    with patch("crawl_engine.runner.run_agent", side_effect=fake_run_agent) as mock_run:
        payload = await execute(request, state)
    mock_run.assert_awaited_once()
    assert payload["meta"]["pages_collected"] == 1
    assert payload["meta"]["seed_url"] == "https://cafef.vn"


@pytest.mark.asyncio
async def test_execute_excludes_html_and_raw_markdown():
    request = CrawlRequest(seed_url="https://cafef.vn")
    page = _page()
    page.html = "<html></html>"
    page.raw_markdown = "raw"
    with patch("crawl_engine.runner.fetch_page", AsyncMock(return_value=page)):
        payload = await execute(request, CrawlState())
    assert "html" not in payload["pages"][0]
    assert "raw_markdown" not in payload["pages"][0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/engine/tests/test_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'crawl_engine.runner'` (and `crawl_engine.contract`, created in Task 7 — that is fine; this task creates `runner.py`, and Task 7 creates `contract.py`. To unblock this test now, Task 7 must precede running it. Implement `contract.py` first if running in strict order; otherwise this test fails on the contract import until Task 7. Proceed to Step 3 to create `runner.py`; re-run after Task 7.)

> Ordering note: `runner.py` imports `CrawlRequest` from `contract.py`. If you implement strictly top-to-bottom, do Task 7 (contract) before this task. The plan keeps runner first because it is the higher-level seam; either order works as long as both exist before the suite is green.

- [ ] **Step 3: Create `runner.py`**

```python
"""Execute a crawl request and shape the result payload.

This is the shared seam between the CLI and the HTTP service: both turn a
CrawlRequest into a result payload without knowing about each other.
"""

from __future__ import annotations

from datetime import UTC, datetime

from crawl_engine.agent import CrawlState, run_agent
from crawl_engine.config import AgentConfig
from crawl_engine.contract import CrawlRequest
from crawl_engine.crawler import fetch_page
from crawl_engine.models import PageResult


def _page_record(page: PageResult) -> dict:
    return page.model_dump(exclude={"html", "raw_markdown"})


def _result_payload(pages: list[PageResult], run_meta: dict) -> dict:
    return {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "total_pages": len(pages),
            "successful": sum(page.success for page in pages),
            "failed": sum(not page.success for page in pages),
            **run_meta,
        },
        "pages": [_page_record(page) for page in pages],
    }


def _agent_run_meta(seed_url: str, config: AgentConfig, state: CrawlState) -> dict:
    return {
        "seed_url": seed_url,
        "goal": config.goal,
        "max_depth": config.max_depth,
        "max_pages": config.max_pages,
        "pages_collected": len(state.pages),
        "article_pages_collected": len(state.article_pages),
        "article_pages": state.article_pages,
        "urls_visited": len(state.visited),
        "total_input_tokens": state.total_input_tokens,
        "total_output_tokens": state.total_output_tokens,
        "finish_reason": state.finish_reason,
        "stop_reason": state.stop_reason,
        "frontier_at_finish": state.frontier_at_finish,
    }


def _direct_run_meta(seed_url: str, page: PageResult) -> dict:
    return {
        "seed_url": seed_url,
        "goal": "",
        "max_depth": 0,
        "max_pages": 1,
        "pages_collected": int(page.success),
        "urls_visited": 1,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "finish_reason": "single page fetched",
    }


async def execute(request: CrawlRequest, state: CrawlState) -> dict:
    """Run a crawl from a request, writing progress into `state`, return the payload.

    Args:
        request: The validated crawl request.
        state: A CrawlState the agent path fills as it runs, so callers can read
            live progress. Ignored on the single-page direct-fetch path.

    Returns:
        The result payload dict with "meta" and "pages".
    """
    config = request.to_agent_config()
    seed = request.seed_url
    if not config.goal and not config.extract_prompt:
        page = await fetch_page(seed, css_selector=config.css_selector or None)
        return _result_payload([page], _direct_run_meta(seed, page))
    await run_agent(seed, config, state=state)
    return _result_payload(state.pages, _agent_run_meta(seed, config, state))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/engine/tests/test_runner.py -q` (after Task 7 exists)
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add runner.execute seam producing result payloads"
```

---

## Task 6: Point the CLI at `runner` + `serialize_payload`

**Files:**
- Modify: `packages/engine/src/crawl_engine/cli.py`
- Modify: `packages/engine/tests/test_main_run.py`

The CLI's `run()` currently calls `fetch_page`/`run_agent` and `write_results` directly. Replace that body with a single `execute()` call plus `serialize_payload`, keeping argument parsing, the depth-ceiling guard, and schema-file loading unchanged.

- [ ] **Step 1: Update the existing CLI run tests**

In `packages/engine/tests/test_main_run.py`, the agent-path tests patch `main.run_agent`/`main.fetch_page`. Replace those with a single patch of `crawl_engine.cli.execute`. Replace the bodies of `test_run_agent_wires_week_3_config_flags`, `test_run_agent_wires_week_4_extraction_config`, and `test_run_direct_fetch_writes_single_page_result` with assertions on the `CrawlRequest` passed to `execute` and on `serialize_payload` output written to disk. Example replacement for the agent-config test:

```python
@pytest.mark.asyncio
async def test_run_builds_request_from_flags(tmp_path):
    out = tmp_path / "out.json"
    args = build_parser().parse_args([
        "https://cafef.vn", "--goal", "collect economy news",
        "--max-depth", "2", "--max-pages", "5", "--output", str(out),
    ])
    payload = {"meta": {"total_pages": 0}, "pages": []}
    with (
        patch("crawl_engine.cli.configure_logging"),
        patch("crawl_engine.cli.execute", AsyncMock(return_value=payload)) as mock_exec,
    ):
        await run(args)
    request = mock_exec.call_args.args[0]
    assert request.seed_url == "https://cafef.vn"
    assert request.goal == "collect economy news"
    assert request.max_depth == 2
    assert out.read_text(encoding="utf-8")  # payload written
```

Keep `test_run_max_depth_above_ceiling_skips_agent`, `test_run_negative_max_depth_skips_agent`, and `test_run_missing_extract_schema_file_skips_agent`, updating their patch targets to `crawl_engine.cli.execute` (asserting it is NOT awaited).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/engine/tests/test_main_run.py -q`
Expected: FAIL — `execute`/`CrawlRequest` not used by `cli.py` yet.

- [ ] **Step 3: Rewrite the CLI `run()` body**

In `cli.py`, update imports and replace the post-validation body of `run()`:

```python
from crawl_engine.agent import CrawlState
from crawl_engine.config import MAX_DEPTH_CEILING, AgentConfig  # AgentConfig kept for type only
from crawl_engine.contract import CrawlRequest
from crawl_engine.output import serialize_payload
from crawl_engine.runner import execute
```

```python
async def run(args: argparse.Namespace) -> None:
    """Run the crawler from parsed command-line arguments."""
    configure_logging(args.verbose)

    if not 0 <= args.max_depth <= MAX_DEPTH_CEILING:
        logger.error(
            "max-depth out of range", max_depth=args.max_depth, ceiling=MAX_DEPTH_CEILING
        )
        return

    extract_schema = None
    if args.extract_schema:
        schema_path = Path(args.extract_schema)
        if not schema_path.exists():
            logger.error("extract schema file not found", path=args.extract_schema)
            return
        extract_schema = json.loads(schema_path.read_text(encoding="utf-8"))

    request = CrawlRequest(
        seed_url=args.url,
        goal=args.goal,
        extract_prompt=args.extract_prompt,
        extract_schema=extract_schema,
        max_depth=args.max_depth,
        max_pages=args.max_pages,
        token_budget=args.token_budget,
        same_domain=args.same_domain,
        include_patterns=args.include_pattern,
        exclude_patterns=args.exclude_pattern,
        date_filter=args.date_filter,
        include_undated=args.include_undated,
        css_selector=args.css_selector,
        max_chars=args.max_chars,
    )

    logger.info("running crawl", seed_url=args.url, goal=args.goal or None)
    payload = await execute(request, CrawlState())

    fmt = args.format
    Path(args.output).write_text(serialize_payload(payload, fmt), encoding="utf-8")
    logger.info(
        "crawl done",
        pages=payload["meta"]["total_pages"],
        output=args.output,
    )
```

Leave `build_parser()` and `main()` unchanged.

- [ ] **Step 4: Run tests and lint**

Run: `uv run pytest -m "not integration" -q`
Expected: PASS.
Run: `uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: CLI runs crawls through runner.execute"
```

---

## Task 7: Create the API contract (`contract.py`)

**Files:**
- Create: `packages/engine/src/crawl_engine/contract.py`
- Test: `packages/engine/tests/test_contract.py`

- [ ] **Step 1: Write the failing test**

Create `packages/engine/tests/test_contract.py`:

```python
"""Tests for crawl_engine.contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crawl_engine.config import AgentConfig
from crawl_engine.contract import CrawlRequest, JobProgress, JobResult, JobStatus


def test_crawl_request_maps_to_agent_config():
    request = CrawlRequest(seed_url="https://cafef.vn", goal="news", max_depth=2)
    config = request.to_agent_config()
    assert isinstance(config, AgentConfig)
    assert config.goal == "news"
    assert config.max_depth == 2


def test_crawl_request_rejects_depth_above_ceiling():
    with pytest.raises(ValidationError):
        CrawlRequest(seed_url="https://cafef.vn", max_depth=6)


def test_crawl_request_requires_seed_url():
    with pytest.raises(ValidationError):
        CrawlRequest()


def test_job_result_defaults_to_zero_progress():
    result = JobResult(status=JobStatus.running)
    assert result.progress == JobProgress(pages_collected=0)
    assert result.payload is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/engine/tests/test_contract.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'crawl_engine.contract'`

- [ ] **Step 3: Create `contract.py`**

```python
"""HTTP API request/response models. These drive the OpenAPI schema."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from crawl_engine.config import MAX_DEPTH_CEILING, AgentConfig


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
        """Build the internal AgentConfig from this request."""
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


class JobStatus(str, Enum):
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/engine/tests/test_contract.py packages/engine/tests/test_runner.py -q`
Expected: PASS (contract 4 + runner 3).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add HTTP API contract models"
```

---

## Task 8: Create the FastAPI service (`service.py`)

**Files:**
- Create: `packages/engine/src/crawl_engine/service.py`
- Test: `packages/engine/tests/test_service.py`

- [ ] **Step 1: Write the failing test**

Create `packages/engine/tests/test_service.py`:

```python
"""Tests for crawl_engine.service via an in-process ASGI client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from crawl_engine.service import create_app

_PAYLOAD = {"meta": {"total_pages": 1, "successful": 1, "failed": 0}, "pages": [{"url": "https://a"}]}


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _poll_until_terminal(client: httpx.AsyncClient, job_id: str) -> dict:
    for _ in range(50):
        body = (await client.get(f"/crawl/{job_id}")).json()
        if body["status"] in ("done", "error"):
            return body
        await asyncio.sleep(0.02)
    raise AssertionError("job did not finish")


@pytest.mark.asyncio
async def test_healthz_ok():
    async with _client(create_app()) as client:
        resp = await client.get("/healthz")
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_crawl_job_runs_to_done_and_returns_payload():
    app = create_app()
    with patch("crawl_engine.service.execute", AsyncMock(return_value=_PAYLOAD)):
        async with _client(app) as client:
            created = (await client.post("/crawl", json={"seed_url": "https://a"})).json()
            body = await _poll_until_terminal(client, created["job_id"])
    assert body["status"] == "done"
    assert body["payload"]["meta"]["total_pages"] == 1


@pytest.mark.asyncio
async def test_crawl_job_records_error():
    app = create_app()
    with patch("crawl_engine.service.execute", AsyncMock(side_effect=RuntimeError("boom"))):
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
        resp = await client.post("/crawl", json={"seed_url": "https://a", "max_depth": 6})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_result_download_json_and_jsonl():
    app = create_app()
    with patch("crawl_engine.service.execute", AsyncMock(return_value=_PAYLOAD)):
        async with _client(app) as client:
            created = (await client.post("/crawl", json={"seed_url": "https://a"})).json()
            await _poll_until_terminal(client, created["job_id"])
            jid = created["job_id"]
            j = await client.get(f"/crawl/{jid}/result", params={"format": "json"})
            l = await client.get(f"/crawl/{jid}/result", params={"format": "jsonl"})
    assert j.status_code == 200 and j.json()["meta"]["total_pages"] == 1
    assert l.status_code == 200 and l.text.strip().startswith("{")


@pytest.mark.asyncio
async def test_result_unavailable_while_running():
    app = create_app()
    gate = asyncio.Event()

    async def slow(request, state):
        await gate.wait()
        return _PAYLOAD

    with patch("crawl_engine.service.execute", slow):
        async with _client(app) as client:
            created = (await client.post("/crawl", json={"seed_url": "https://a"})).json()
            await asyncio.sleep(0.02)  # let the job reach "running"
            resp = await client.get(f"/crawl/{created['job_id']}/result")
            assert resp.status_code == 404
            gate.set()
            await _poll_until_terminal(client, created["job_id"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/engine/tests/test_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'crawl_engine.service'`

- [ ] **Step 3: Create `service.py`**

```python
"""FastAPI service exposing the crawl engine as polled async jobs."""

from __future__ import annotations

import asyncio
import os
import time
from uuid import uuid4

import structlog
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from crawl_engine.agent import CrawlState
from crawl_engine.contract import (
    CrawlRequest,
    JobCreated,
    JobProgress,
    JobResult,
    JobStatus,
)
from crawl_engine.output import serialize_payload
from crawl_engine.runner import execute

logger = structlog.get_logger(__name__)

JOB_TTL_SECONDS = 3600


class Job:
    """One crawl job and its mutable state."""

    def __init__(self, request: CrawlRequest) -> None:
        self.request = request
        self.state = CrawlState()
        self.status = JobStatus.queued
        self.payload: dict | None = None
        self.error: str | None = None
        self.created_at = time.monotonic()
        self.task: asyncio.Task | None = None

    def to_result(self) -> JobResult:
        return JobResult(
            status=self.status,
            progress=JobProgress(pages_collected=len(self.state.pages)),
            payload=self.payload,
            error=self.error,
        )


def create_app() -> FastAPI:
    """Build the FastAPI application with its own job registry and lock."""
    app = FastAPI(title="crawl-engine", version="0.1.0")

    origins = [o for o in os.environ.get("CORS_ALLOW_ORIGINS", "*").split(",") if o]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    jobs: dict[str, Job] = {}
    run_lock = asyncio.Lock()

    def purge_expired() -> None:
        cutoff = time.monotonic() - JOB_TTL_SECONDS
        for jid in [
            jid
            for jid, job in jobs.items()
            if job.status in (JobStatus.done, JobStatus.error) and job.created_at < cutoff
        ]:
            del jobs[jid]

    async def run_job(job_id: str) -> None:
        job = jobs[job_id]
        async with run_lock:
            job.status = JobStatus.running
            try:
                job.payload = await execute(job.request, job.state)
                job.status = JobStatus.done
            except Exception as exc:  # noqa: BLE001
                job.error = str(exc)
                job.status = JobStatus.error
                logger.warning("crawl job failed", job_id=job_id, error=str(exc))

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.post("/crawl")
    async def start_crawl(request: CrawlRequest) -> JobCreated:
        purge_expired()
        job_id = uuid4().hex
        job = Job(request)
        jobs[job_id] = job
        job.task = asyncio.create_task(run_job(job_id))
        return JobCreated(job_id=job_id)

    @app.get("/crawl/{job_id}")
    async def get_crawl(job_id: str) -> JobResult:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job.to_result()

    @app.get("/crawl/{job_id}/result")
    async def get_result(job_id: str, format: str = "json") -> Response:
        job = jobs.get(job_id)
        if job is None or job.status != JobStatus.done or job.payload is None:
            raise HTTPException(status_code=404, detail="result not available")
        fmt = "jsonl" if format == "jsonl" else "json"
        body = serialize_payload(job.payload, fmt)
        media = "application/x-ndjson" if fmt == "jsonl" else "application/json"
        filename = f"crawl-{job_id}.{fmt}"
        return Response(
            content=body,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return app


app = create_app()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/engine/tests/test_service.py -q`
Expected: PASS.
Run: `uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: FastAPI service with polled async crawl jobs"
```

---

## Task 9: Create the Gradio engine client (`client.py`)

**Files:**
- Create: `packages/gradio/src/crawl_gradio/client.py`
- Test: `packages/gradio/tests/test_client.py`

- [ ] **Step 1: Write the failing test**

Create `packages/gradio/tests/test_client.py` (uses `pytest_httpx`'s `httpx_mock` fixture, already in dev deps):

```python
"""Tests for crawl_gradio.client."""

from __future__ import annotations

import pytest

from crawl_gradio import client


@pytest.mark.asyncio
async def test_start_crawl_posts_and_returns_job_id(httpx_mock):
    httpx_mock.add_response(method="POST", url="http://engine/crawl", json={"job_id": "abc"})
    job_id = await client.start_crawl({"seed_url": "https://a"}, base_url="http://engine")
    assert job_id == "abc"


@pytest.mark.asyncio
async def test_poll_until_done_yields_until_terminal(httpx_mock):
    httpx_mock.add_response(url="http://engine/crawl/abc", json={"status": "running", "progress": {"pages_collected": 1}})
    httpx_mock.add_response(url="http://engine/crawl/abc", json={"status": "done", "payload": {"meta": {}, "pages": []}})
    seen = [s["status"] async for s in client.poll_until_done("abc", base_url="http://engine", interval=0)]
    assert seen == ["running", "done"]


@pytest.mark.asyncio
async def test_download_result_returns_bytes(httpx_mock):
    httpx_mock.add_response(url="http://engine/crawl/abc/result?format=json", content=b"{}")
    data = await client.download_result("abc", "json", base_url="http://engine")
    assert data == b"{}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/gradio/tests/test_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'crawl_gradio.client'`

- [ ] **Step 3: Create `client.py`**

```python
"""Async HTTP client for the crawl engine. The only UI→engine coupling."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import httpx

ENGINE_URL = os.environ.get("ENGINE_URL", "http://localhost:8000")
POLL_SECONDS = 2.0


async def start_crawl(request: dict, *, base_url: str = ENGINE_URL) -> str:
    """POST a crawl request and return the job id."""
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        resp = await http.post("/crawl", json=request)
        resp.raise_for_status()
        return resp.json()["job_id"]


async def get_status(job_id: str, *, base_url: str = ENGINE_URL) -> dict:
    """GET the current job status."""
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        resp = await http.get(f"/crawl/{job_id}")
        resp.raise_for_status()
        return resp.json()


async def poll_until_done(
    job_id: str, *, base_url: str = ENGINE_URL, interval: float = POLL_SECONDS
) -> AsyncIterator[dict]:
    """Yield job status dicts until the job is done or errored."""
    while True:
        status = await get_status(job_id, base_url=base_url)
        yield status
        if status["status"] in ("done", "error"):
            return
        await asyncio.sleep(interval)


async def download_result(
    job_id: str, fmt: str = "json", *, base_url: str = ENGINE_URL
) -> bytes:
    """Download the serialized result artifact."""
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as http:
        resp = await http.get(f"/crawl/{job_id}/result", params={"format": fmt})
        resp.raise_for_status()
        return resp.content
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/gradio/tests/test_client.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add crawl_gradio engine HTTP client"
```

---

## Task 10: Refactor the Gradio `run_crawl` into a polling generator (remove engine imports)

**Files:**
- Modify: `packages/gradio/src/crawl_gradio/ui.py`
- Modify: `packages/gradio/src/crawl_gradio/app.py`
- Modify: `packages/gradio/tests/test_ui.py`

After this task the Gradio package imports nothing from `crawl_engine`.

- [ ] **Step 1: Update the run_crawl tests to the client-based flow**

In `packages/gradio/tests/test_ui.py`, replace any test that patched `crawl_gradio.ui.run_agent` / `crawl_gradio.ui.fetch_page` / `crawl_gradio.ui.write_results` with tests that patch the client functions. Add:

```python
import pytest

from crawl_gradio import ui


@pytest.mark.asyncio
async def test_run_crawl_polls_then_renders(monkeypatch, tmp_path):
    payload = {"meta": {"total_pages": 1, "successful": 1, "failed": 0}, "pages": []}

    async def fake_poll(job_id, **kwargs):
        yield {"status": "running", "progress": {"pages_collected": 0}}
        yield {"status": "done", "payload": payload}

    monkeypatch.setattr(ui, "start_crawl", _async_return("job1"))
    monkeypatch.setattr(ui, "poll_until_done", fake_poll)
    monkeypatch.setattr(ui, "download_result", _async_return(b"{}"))
    monkeypatch.setattr(ui, "_output_path", lambda fmt: str(tmp_path / f"out.{fmt}"))

    frames = [
        frame
        async for frame in ui.run_crawl(
            "https://cafef.vn", "collect news", "", "", 1, 5, 500000, True,
            "", "", "", False, "", 0, "json",
        )
    ]
    statuses = [f[0] for f in frames]
    assert any("Running" in s for s in statuses)
    assert "Collected 1 page" in statuses[-1]


def _async_return(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn
```

Keep `test_ui_results.py` and `test_dev_ui.py` as moved; update only their import paths if not already done in Task 1.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/gradio/tests/test_ui.py::test_run_crawl_polls_then_renders -q`
Expected: FAIL — `run_crawl` is still the in-process coroutine, not a generator using the client.

- [ ] **Step 3: Rewrite the top-of-file imports in `ui.py`**

Remove these engine imports from `ui.py`:

```python
from crawl_engine.agent import AgentConfig, CrawlState, run_agent
from crawl_engine.crawler import fetch_page
from crawl_engine.models import PageResult
from crawl_engine.output import write_results
```

Add:

```python
import httpx

from crawl_gradio.client import download_result, poll_until_done, start_crawl
```

Delete the now-unused helpers `_build_config`, `_page_record`, `_result_payload`, `_agent_run_meta`, `_direct_run_meta` from `ui.py` (they live in the engine's `runner.py` now). Keep `_s`, `_validate_url`, `_parse_schema`, `_parse_patterns`, `_output_path`.

- [ ] **Step 4: Add `_build_request` and rewrite `run_crawl`**

Add the request builder near the other helpers:

```python
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
```

Replace the entire `run_crawl` function with the polling generator:

```python
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
):
    """Drive a crawl over HTTP, yielding progress then the final result view.

    Yields tuples of:
        (status, table html, payload state, json preview, extraction_requested, download path)
    """
    url = _validate_url(seed_url)
    request = _build_request(
        url, goal, extract_prompt, extract_schema, max_depth, max_pages, token_budget,
        same_domain, include_patterns, exclude_patterns, date_filter, include_undated,
        css_selector, max_chars,
    )
    extraction_requested = bool(_s(extract_prompt) or _s(extract_schema))
    hold = (gr.update(), gr.update(), gr.update(), gr.update(), gr.update())

    try:
        job_id = await start_crawl(request)
    except httpx.HTTPError as exc:
        yield (f"Engine error: {exc}", *hold)
        return

    status: dict = {}
    async for status in poll_until_done(job_id):
        if status["status"] == "running":
            collected = status.get("progress", {}).get("pages_collected", 0)
            yield (f"Running — {collected} page(s) collected…", *hold)

    if status.get("status") == "error":
        yield (f"Crawl failed: {status.get('error')}", *hold)
        return

    payload = status["payload"]
    table = build_result_table(payload, "Extracted", extraction_requested=extraction_requested)
    table_html = render_result_table_html(table)
    meta = payload["meta"]
    status_msg = (
        f"Collected {meta['total_pages']} page(s), "
        f"{meta['successful']} successful, {meta['failed']} failed."
    )

    fmt = output_format.lower()
    data = await download_result(job_id, fmt)
    path = _output_path(fmt)
    Path(path).write_bytes(data)

    yield (status_msg, table_html, payload, payload, extraction_requested, path)
```

Leave `build_demo` and its `run_button.click(fn=run_crawl, ...)` wiring unchanged — Gradio runs an async generator the same way it runs a coroutine.

- [ ] **Step 5: Replace the engine logging import in `app.py`**

In `packages/gradio/src/crawl_gradio/app.py`, remove `from crawl_engine.logging_config import configure_logging` and use stdlib logging plus a container-friendly launch:

```python
"""Launch the Crawl Tool Gradio interface."""

import logging

from crawl_gradio.ui import _RESULT_JS, CUSTOM_CSS, build_demo


def main() -> None:
    """Configure logging and launch the web interface."""
    logging.basicConfig(level=logging.INFO)
    build_demo().queue(default_concurrency_limit=1).launch(
        server_name="0.0.0.0", server_port=7860, css=CUSTOM_CSS, js=_RESULT_JS
    )


if __name__ == "__main__":
    main()
```

If `dev_ui.py` imports `crawl_engine.logging_config`, replace it there too with `logging.basicConfig(level=logging.INFO)`.

- [ ] **Step 6: Run tests and lint**

Run: `uv run pytest -m "not integration" -q`
Expected: PASS.
Run: `uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: Gradio talks to the engine over HTTP only"
```

---

## Task 11: Boundary test — the UI must not import the engine

**Files:**
- Test: `packages/gradio/tests/test_boundary.py`

- [ ] **Step 1: Write the failing test**

Create `packages/gradio/tests/test_boundary.py`:

```python
"""The Gradio package must not import the engine or its heavy dependencies."""

from __future__ import annotations

import ast
from pathlib import Path

import crawl_gradio

_FORBIDDEN = ("crawl_engine", "crawl4ai", "playwright", "anthropic")
_PKG_DIR = Path(crawl_gradio.__file__).parent


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_engine_imports_in_gradio_package():
    offenders: dict[str, set[str]] = {}
    for py in _PKG_DIR.rglob("*.py"):
        bad = _imported_roots(py) & set(_FORBIDDEN)
        if bad:
            offenders[py.name] = bad
    assert not offenders, f"forbidden imports found: {offenders}"
```

- [ ] **Step 2: Run test to verify it passes (Task 10 already removed the imports)**

Run: `uv run pytest packages/gradio/tests/test_boundary.py -q`
Expected: PASS. If it FAILS, the offender map names the file and import still referencing the engine — remove that import before continuing.

> This is the static-analysis equivalent of the spec's "imports succeed with crawl4ai absent." The Docker build in Task 12 is the runtime proof, since the Gradio image never installs crawl4ai.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "test: assert Gradio package imports nothing from the engine"
```

---

## Task 12: Dockerfiles and docker-compose

**Files:**
- Create: `packages/engine/Dockerfile`, `packages/gradio/Dockerfile`, `docker-compose.yml`, `.env.example`

- [ ] **Step 1: Write the engine Dockerfile**

Create `packages/engine/Dockerfile`:

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "crawl_engine.service:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write the Gradio Dockerfile**

Create `packages/gradio/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .

EXPOSE 7860
CMD ["python", "-m", "crawl_gradio.app"]
```

- [ ] **Step 3: Write `docker-compose.yml`** (repo root)

```yaml
services:
  engine:
    build: ./packages/engine
    environment:
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY}
      CORS_ALLOW_ORIGINS: ${CORS_ALLOW_ORIGINS:-*}
    ports:
      - "8000:8000"

  gradio:
    build: ./packages/gradio
    environment:
      ENGINE_URL: http://engine:8000
    ports:
      - "7860:7860"
    depends_on:
      - engine
```

- [ ] **Step 4: Write `.env.example`** (repo root)

```bash
ANTHROPIC_API_KEY=sk-ant-...
CORS_ALLOW_ORIGINS=*
```

- [ ] **Step 5: Validate the compose file**

Run: `docker compose config`
Expected: prints the resolved config with no errors (does not build images).

> Full `docker compose build` requires Docker and network access for base images; run it if available. The compose file is structured so the engine image carries Chromium and the Anthropic key, and the Gradio image carries neither.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "build: add engine and gradio Dockerfiles and compose"
```

---

## Task 13: Update documentation

**Files:**
- Modify: `README.md`, `docs/architecture.md`

- [ ] **Step 1: Update `README.md`**

Replace the Project Structure section with the two-package layout from this plan's File Structure. Add a "Running with Docker" section:

```markdown
## Running with Docker

```bash
cp .env.example .env          # set ANTHROPIC_API_KEY
docker compose up --build
# Gradio UI:    http://localhost:7860
# Engine API:   http://localhost:8000/docs
```
```

Add a "Engine API" subsection noting the endpoints (`POST /crawl`, `GET /crawl/{id}`, `GET /crawl/{id}/result`) and that any HTTP client — including a non-Python frontend — can drive the engine via the OpenAPI schema at `/openapi.json`. Update the CLI invocation to `uv run crawl-tool <url> ...` (the console script) or `uv run python -m crawl_engine.cli <url> ...`.

- [ ] **Step 2: Update `docs/architecture.md`**

Replace the module diagram with the two-package, HTTP-boundary architecture: `crawl_gradio` → (HTTP) → `crawl_engine` (`service` → `runner` → `agent`/`crawler`/`extractor`). Document the job lifecycle (queued → running → done/error, serialized behind a lock, in-memory, TTL-purged) and the contract endpoints. Note that `crawl_gradio` shares no Python code with `crawl_engine` and that a future non-Python frontend is a separate repo on the same contract.

- [ ] **Step 3: Verify the full suite and lint one final time**

Run: `uv run pytest -m "not integration" -q`
Expected: PASS.
Run: `uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: document two-package API architecture and Docker usage"
```

---

## Self-Review Notes (for the implementer)

- **Spec coverage:** Workspace split (Task 1), engine OpenAPI service (Tasks 7–8), async job + polling (Task 8 + Task 10), result-download endpoint (Task 8), CORS (Task 8), pure-HTTP Gradio client (Tasks 9–10), boundary enforcement (Task 11), Docker images + compose (Task 12), docs (Task 13). Live progress is served via the injected `CrawlState` (Task 4) read in `Job.to_result()` (Task 8).
- **Task ordering caveat:** `runner.py` (Task 5) imports `contract.py` (Task 7). If implementing strictly in order, create `contract.py` before running the `runner` and `service` test suites. Both must exist before the suite is green.
- **Shared-venv note:** in the dev workspace both packages are installed, so the boundary is enforced by the static-import test (Task 11), not by crawl4ai being absent. True runtime isolation is proven by the Gradio Docker image, which never installs crawl4ai.
- **Test migration:** Tasks 1, 6, and 10 update existing tests whose patch targets or import paths changed (`src.*` → `crawl_engine.*`/`crawl_gradio.*`, `main` → `crawl_engine.cli`, in-process engine calls → client/`execute`). Run the full suite after each to catch stragglers.
```
