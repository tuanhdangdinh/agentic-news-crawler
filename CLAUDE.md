# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv run python -m pytest                              # run all unit tests
uv run python -m pytest tests/engine/test_agent_run_agent.py   # run a single test file
uv run python -m pytest -k "test_name"              # run a single test by name
uv run ruff check .                                 # lint
uv run ruff format .                                # format
uv run crawl-tool <url> --goal "..." --max-depth 1 --max-pages 10
```

Always use `uv` — never `pip` directly.

## Structure

```
src/crawl_tool/
├── engine/      # crawl engine — FastAPI service, agent loop, crawler, extractor
└── gradio/      # Gradio UI — calls engine over HTTP

tests/
├── engine/      # unit tests for engine
└── gradio/      # unit tests for Gradio UI

docker/
├── Dockerfile.engine
├── Dockerfile.gradio
└── docker-compose.yml
```

The Gradio UI and engine run as separate Docker containers. The UI calls the engine over HTTP — it never imports from `crawl_tool.engine` directly.

## Architecture

The crawler is an **observe → decide → act** agent loop. Claude drives every crawl decision; hard guardrails (depth, domain, token budget) are enforced in code and cannot be overridden by the agent.

**Data flow:**

```
execute() → run_agent() → fetch_page() → _agent_turn() → Claude API
                                                        ↓ tool calls
                                           add_to_frontier / extract / finish
```

**Engine module responsibilities:**

| Module | Role |
|---|---|
| `engine/models.py` | `PageResult` — shared domain type used by every module |
| `engine/crawler.py` | Thin Crawl4AI wrapper. Only module that touches crawl4ai. Returns `PageResult`. |
| `engine/proxy.py` | `ManagedProxySession` — job-scoped sticky proxy sessions per domain. `ProxySettings` reads from env. |
| `engine/agent.py` | Agent loop: `run_agent()`, `AgentConfig`, `CrawlState`. Contains all guardrail logic (`_allowed`, `_canonical`, `_is_article_page`, `_parse_min_articles`). |
| `engine/extractor.py` | Claude-powered structured extraction. `extract()` calls Claude with a JSON Schema, validates output with `jsonschema`. `infer_schema()` derives a schema from a natural-language prompt. |
| `engine/schema_registry.py` | Deterministic intent matching. `match_registered_schema(prompt)` returns `(name, schema_copy)` or `None`. Called before `infer_schema` so known intents skip an LLM call entirely. |
| `engine/logging_config.py` | `configure_logging(verbose)` — sets up structlog JSON output. Field order: `timestamp`, `level`, `logger`, `event`, then remaining fields alphabetically. |
| `engine/date_filter.py` | `parse_date_filter()` → `tuple[date, date]`. `detect_page_date()` checks meta tags, JSON-LD, Last-Modified header, then Vietnamese URL pattern. `is_in_range()` applies the filter. |
| `engine/output.py` | `write_results()` → JSON or JSONL. Strips `html` and `raw_markdown` from output. |
| `engine/prompts.py` | Jinja2 loader with `StrictUndefined`. Templates live in `engine/prompts/*.j2`. |
| `engine/runner.py` | `execute()` — entry point called by the service. Creates `ManagedProxySession` from env and threads it through both fetch paths. |
| `engine/service.py` | FastAPI app with `/crawl` (POST), `/crawl/{id}` (GET), `/crawl/{id}/result` (GET). |
| `engine/contract.py` | `CrawlRequest`, `JobResult`, `JobStatus` — Pydantic models for the HTTP API. |
| `engine/config.py` | `AgentConfig` — internal crawl parameters. |
| `engine/cli.py` | CLI entry point (`crawl-tool` command). |

## Key Behaviours to Know

**Finish guard:** `finish` is rejected if the frontier has reachable URLs, or if the goal specifies a minimum article count and fewer have been collected. Claude receives a rejection message and the crawl continues.

**Auto-extraction:** If `--extract-prompt` is set and Claude did not call `extract` during its turn, the agent loop auto-extracts from article pages after the turn completes.

**Schema resolution order:** explicit `--extract-schema` file → `match_registered_schema()` on the prompt → `infer_schema()` LLM call. The registry match happens once at loop start and also at the `extract` tool call site when no schema has been set yet. Adding a new registered intent requires only touching `schema_registry.py`.

**Article classification:** `_is_article_page()` checks for `article:published_time` in metadata, or a Vietnamese URL pattern (`/slug-NNNNNNNNN.chn`). Classified articles are tracked in `state.article_pages`.

**Token/page budgets** are checked at the top of each loop iteration, before fetching.

**Proxy:** `ManagedProxySession` is created once per `execute()` call when `PROXY_URL` is set. It is threaded via keyword-only `proxy_session` params through `run_agent → fetch_page → _fetch_with_retries`. Credentials never appear in logs, API payloads, or `PageResult`.

## Tooling

- Ruff: line-length 100, rules E/F/I/UP/B/SIM (configured in `pyproject.toml`)
- All public functions require type hints; use `X | Y` not `Optional[X]`
- All I/O is `async`; use `AsyncAnthropic` and `AsyncWebCrawler` — never sync equivalents
- Models default to `claude-haiku-4-5-20251001` (agent and extractor)
- `ANTHROPIC_API_KEY` must be set in environment or `.env`
- Run tests with `uv run python -m pytest` (not `uv run pytest`) to ensure the venv is used

## Git

- Commit messages: subject line only — no body paragraph, no `Co-Authored-By`
- Follow Conventional Commits: `type: summary` (e.g. `refactor: restructure into single-package layout`)

## Standards

Before writing code or docs, read the relevant standard:

- `docs/standards/coding_style.md` — type hints, async rules, modular design, error handling
- `docs/standards/doc_style.md` — document templates, report structure, commit messages, docstring format
