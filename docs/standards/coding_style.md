# Coding Style Guide

---

## Tooling

- **Linter/formatter**: Ruff — run `uv run ruff check .` and `uv run ruff format .` before every commit
- **Tests**: `uv run pytest`
- **Config**: `pyproject.toml` — line-length 100, rules E/F/I/UP/B/SIM
- **Package manager**: `uv` only — never `pip install`

---

## Scope

Do exactly what the task asks. Do not:

- Add features, flags, or parameters not mentioned in the task
- Refactor surrounding code while fixing a bug
- Add error handling for cases that cannot happen
- Add backwards-compatibility shims when you can just change the code
- Clean up unrelated style issues in files you touch

---

## Type Hints

Every public function signature must have full type hints.

```python
# correct
async def fetch_page(url: str, css_selector: str | None = None) -> PageResult: ...

# wrong — missing return type, wrong union syntax
async def fetch_page(url, css_selector=None): ...
async def fetch_page(url: str, css_selector: Optional[str] = None): ...
```

Rules:

- Use `X | Y` — never `Optional[X]` or `Union[X, Y]`
- Use `list[str]`, `dict[str, int]` — never `List`, `Dict` from `typing`
- Private functions (`_name`) do not need type hints, but may have them

---

## Async

- All I/O functions must be `async def`
- Use `AsyncAnthropic`, `AsyncWebCrawler` — never the sync client inside an async context
- Never call blocking I/O (`open`, `requests.get`, `time.sleep`) inside an async function

```python
# correct
async def fetch_page(url: str) -> PageResult:
    async with AsyncWebCrawler(config=_BROWSER_CFG) as crawler:
        result = await crawler.arun(url=url, config=cfg)

# wrong — sync client inside async function
async def fetch_page(url: str) -> PageResult:
    crawler = WebCrawler()
    result = crawler.run(url=url)
```

---

## Imports

Order: stdlib → third-party → local, one blank line between groups.

```python
# correct
import asyncio

import anthropic
import structlog
from pydantic import BaseModel

from src.models import PageResult
from src.prompts import render
```

No wildcard imports (`from x import *`). Ruff `I` rules enforce order automatically.

---

## Error Handling

- Functions that can fail must return a result object — never raise across module boundaries

```python
# correct
except Exception as exc:
    return PageResult(success=False, error=str(exc))

# wrong — caller has no way to distinguish expected failures
except Exception:
    pass
```

- Validate only at system boundaries (CLI args, external API responses)
- Trust internal function contracts — do not add defensive checks for arguments that can only come from your own code

---

## Comments

Only comment the **why** — never the what. If the name already explains it, no comment.

```python
# correct — explains a non-obvious constraint
await asyncio.sleep(retry_after)  # respect server's Retry-After before re-attempting

# wrong — restates what the code already says
# sleep for retry_after seconds
await asyncio.sleep(retry_after)
```

One line max. No multi-line comment blocks. No section dividers like `# --- helpers ---`.

---

## Docstrings

Public functions and classes only — Google style.

```python
async def extract(page: PageResult, prompt: str, schema: dict | None = None) -> dict:
    """Extract structured data from a fetched page.

    Args:
        page: Fetched page whose markdown is the primary extraction input.
        prompt: Natural-language instruction describing which fields to extract.
        schema: JSON Schema to validate output. When None, infer_schema is called first.

    Returns:
        Validated extraction dict on success, or {"error": ..., "raw": ...} on failure.
    """
```

Rules:

- One-line summary, blank line, then Args and Returns
- Args and Returns: one short phrase per item — not sentences, not paragraphs
- No docstrings on private functions (`_name`)
- No docstrings that just restate the function name

---

## Naming and Structure

- Constants: `UPPER_SNAKE_CASE` at module level — no magic numbers inline
- One concern per module — `crawler.py` fetches, `agent.py` decides, `extractor.py` extracts, `src/models/` holds shared domain types
- Extract a helper only when it removes real duplication or isolates an external API boundary — not to make the function shorter

---

## Modular Design

- Shared domain types belong in `src/models/` when they represent crawler-wide concepts, not in the module that first created them
- Cross-module reuse is a signal to extract a type, but ownership should follow the domain boundary rather than a fixed usage count
- Modules should depend on stable public interfaces — avoid importing implementation details from sibling modules
- Re-export intentionally public APIs from `__init__.py`; keep internal helpers private to their modules

---

## Logging

Use **structlog** — never `import logging` directly in source modules (only `src/logging_config.py` touches stdlib `logging`).

```python
# correct
import structlog
logger = structlog.get_logger(__name__)

logger.info("fetch ok", url=url, status=status, chars=len(markdown))
logger.warning("fetch failed", url=url, error=page.error)

# wrong — format strings, not structured
import logging
logger = logging.getLogger(__name__)
logger.info("fetch ok: %s status=%s", url, status)
```

Rules:

- Event string is a short, static label — no interpolation in the string itself
- All variable data goes as keyword arguments
- `configure_logging(verbose)` in `src/logging_config.py` is the single place that calls `logging.basicConfig` and `structlog.configure` — call it once from `main.py`
- Tests: call `configure_logging(verbose=True)` in a session-scoped autouse fixture (`conftest.py`) so `caplog` works

---

## Tests

- Mock all external API calls (`anthropic`, `crawl4ai`) in unit tests — no live network in `pytest`
- Test one behaviour per test function; name tests `test_<what>_<condition>`
- Do not add tests for behaviour not requested in the task

---

## Secrets

- Never commit `.env`, API keys, or credentials
- Read secrets from environment variables only

---

## Before Implementing Against an External Library

Use **Context7** or **Exa** MCP to verify current API before writing code.
Training-data knowledge of library APIs is stale — class names, parameter names, and return types change across versions. Do not guess.
