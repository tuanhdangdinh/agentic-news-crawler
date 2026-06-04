# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv run pytest                        # run all unit tests
uv run pytest tests/test_agent.py   # run a single test file
uv run pytest -k "test_name"        # run a single test by name
uv run ruff check .                 # lint
uv run ruff format .                # format
uv run python main.py <url> --goal "..." --max-depth 1 --max-pages 10
```

Always use `uv` — never `pip` directly.

## Architecture

The crawler is an **observe → decide → act** agent loop. Claude drives every crawl decision; hard guardrails (depth, domain, token budget) are enforced in code and cannot be overridden by the agent.

**Data flow:**

```
main.py → run_agent() → fetch_page() → _agent_turn() → Claude API
                                                       ↓ tool calls
                                          add_to_frontier / extract / finish
```

**Module responsibilities:**

| Module | Role |
|---|---|
| `src/models/page.py` | `PageResult` — shared domain type used by every module. Import via `from src.models import PageResult` |
| `src/crawler.py` | Thin Crawl4AI wrapper. Only module that touches crawl4ai. Returns `PageResult`. |
| `src/agent.py` | Agent loop: `run_agent()`, `AgentConfig`, `CrawlState`. Contains all guardrail logic (`_allowed`, `_canonical`, `_is_article_page`, `_parse_min_articles`). |
| `src/extractor.py` | Claude-powered structured extraction. `extract()` calls Claude with a JSON Schema, validates output with `jsonschema`. `infer_schema()` derives a schema from a natural-language prompt. |
| `src/date_filter.py` | `parse_date_filter()` → `tuple[date, date]`. `detect_page_date()` checks meta tags, JSON-LD, Last-Modified header, then Vietnamese URL pattern. `is_in_range()` applies the filter. |
| `src/output.py` | `write_results()` → JSON or JSONL. Strips `html` and `raw_markdown` from output. |
| `src/prompts.py` | Jinja2 loader with `StrictUndefined`. Templates live in `prompts/*.j2`. |
| `prompts/` | `system.j2`, `user_turn.j2`, `extract.j2`, `infer_schema.j2` |

## Key Behaviours to Know

**Finish guard:** `finish` is rejected if the frontier has reachable URLs, or if the goal specifies a minimum article count and fewer have been collected. Claude receives a rejection message and the crawl continues.

**Auto-extraction:** If `--extract-prompt` is set and Claude did not call `extract` during its turn, the agent loop auto-extracts from article pages after the turn completes.

**Schema inference:** When `--extract-prompt` is given without `--extract-schema`, `infer_schema()` is called once before the loop starts and the result is stored in `config.extract_schema`.

**Article classification:** `_is_article_page()` checks for `article:published_time` in metadata, or a Vietnamese URL pattern (`/slug-NNNNNNNNN.chn`). Classified articles are tracked in `state.article_pages`.

**Token/page budgets** are checked at the top of each loop iteration, before fetching.

## Tooling

- Ruff: line-length 100, rules E/F/I/UP/B/SIM (configured in `pyproject.toml`)
- All public functions require type hints; use `X | Y` not `Optional[X]`
- All I/O is `async`; use `AsyncAnthropic` and `AsyncWebCrawler` — never sync equivalents
- Models default to `claude-sonnet-4-6` (agent) and `claude-haiku-4-5-20251001` (extractor)
- `ANTHROPIC_API_KEY` must be set in environment or `.env`

## Git

- Commit messages: subject line only — no body paragraph, no `Co-Authored-By`
- Follow Conventional Commits: `type: summary` (e.g. `refactor: move PageResult to src/models/`)

## Standards

Before writing code or docs, read the relevant standard:

- `docs/standards/coding_style.md` — type hints, async rules, modular design, error handling
- `docs/standards/doc_style.md` — document templates, report structure, commit messages, docstring format
