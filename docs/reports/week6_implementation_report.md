# Week 6 Implementation Report — Testing, Docs, and Handover

**Prepared:** 2026-06-09

**Revision history:**
- Initial draft: integration tests, architecture doc, README update, css-selector flag, max-chars truncation, structured logging migration
- Rev 2 (2026-06-09): recorded the live integration result and corrected the standalone fetch test targets
- Rev 3 (2026-06-10): strengthened acceptance assertions, documented the Gradio and schema-registry paths, and recorded fresh verification

**commit:** [link](https://github.com/tuanhdangdinh/agentic-news-crawler/commit/17b19cd)

---

## Overview

### What Week 6 Builds

- Completes the intern plan's Week 6 contract: integration test suite on three real Vietnamese economy sites, architecture document, and README CLI reference update
- Adds `--css-selector` flag — the outstanding Week 5 entry criterion; wired end-to-end through CLI → `AgentConfig` → `fetch_page`
- Adds `--max-chars` to cap per-page markdown sent to Claude, providing direct control over per-turn token cost
- Migrates all remaining `print()` calls to structured `structlog` events and adds stable JSON field ordering

### What Changed From Week 5

- `tests/test_integration.py` — new file; 11 end-to-end tests across CafeF, VnEconomy, and VietnamPlus covering crawl completion, depth correctness, deduplication, same-domain filter, date filter, and extraction accuracy; marked `@pytest.mark.integration` and excluded from the default `pytest` run
- `docs/architecture.md` — new file; module diagram, data flow diagram, key design decisions, `AgentConfig` and `CrawlState` field references, date detection priority order, known limitations
- `README.md` — project structure updated to reflect current layout; `--css-selector` and `--max-chars` added to CLI reference
- `src/agent.py` — `AgentConfig` gains `css_selector` and `max_chars`; `_agent_turn` truncates markdown before rendering; `run_agent` forwards `css_selector` to `fetch_page`; all `print()` calls replaced with `logger` events; docstrings added to public functions
- `src/logging_config.py` — `_order_log_fields` processor added; `timestamp/level/logger/event` always first, remaining keys alphabetical
- `main.py` — `--css-selector` and `--max-chars` flags added; all `print()` calls replaced with `logger` events; docstrings added
- `pyproject.toml` — `integration` and `slow` pytest markers registered
- `tests/` — 189 passing unit tests (up from 176); new: `test_logging_config.py`; expanded: `test_agent_run_agent.py`, `test_main_build_parser.py`

Post-week Rev 3 updates:

- `tests/test_integration.py` — depth and dedup assertions now inspect real fetch calls; domain checks normalize hostnames; date filtering requires a dated article; extraction requires title, publish date, author, and summary
- `docs/architecture.md` — current-state diagrams now include the Gradio interface and registered-schema-first extraction flow
- `README.md` — current-state usage now documents the Gradio launcher and schema precedence
- `.gitignore` — failed-run logs and integration result artifacts are excluded from source control

### Data Flow This Week

```mermaid
flowchart TD
    CLI["main.py\n--css-selector --max-chars"]
    CONFIG["AgentConfig\ncss_selector · max_chars"]
    AGENT["src/agent.py\n_agent_turn — markdown truncation"]
    CRAWLER["src/crawler.py\nfetch_page(css_selector)"]
    CLAUDE["Claude API\nreceives ≤ max_chars markdown"]
    LOG["src/logging_config.py\nstable field ordering"]
    INTEG["tests/test_integration.py\nend-to-end on 3 real sites"]
    ARCH["docs/architecture.md\nmodule diagram · design decisions"]

    CLI -->|"css_selector, max_chars"| CONFIG
    CONFIG -->|"css_selector"| CRAWLER
    CONFIG -->|"max_chars"| AGENT
    CRAWLER -->|"PageResult"| AGENT
    AGENT -->|"truncated markdown"| CLAUDE
    AGENT -->|"logger calls"| LOG
    INTEG -.->|"exercises"| AGENT
    ARCH -.->|"documents"| AGENT
```

### This Report

Documents the Week 6 deliverables: integration test suite, architecture document, README update, `--css-selector` flag, `--max-chars` truncation, and structured logging migration.

---

## Objective

- Write `tests/test_integration.py` — end-to-end coverage of the intern plan's functional acceptance criteria on three real Vietnamese economy sites
- Write `docs/architecture.md` — module diagram, data flow, design decisions, and field reference
- Update `README.md` — project structure, CLI reference, and examples to reflect current state
- Wire `--css-selector` end-to-end through CLI → `AgentConfig` → `fetch_page`
- Add `--max-chars` flag to cap markdown sent to Claude per agent turn
- Replace all remaining `print()` calls with structured `structlog` events; add stable JSON field ordering
- Reach 189 passing unit tests; `uv run pytest -m "not integration"` exits 0

---

## Module: `tests/test_integration.py`

### Design Decisions

- **Marked `@pytest.mark.integration` and excluded from default run** — integration tests require live internet and a valid `ANTHROPIC_API_KEY`; running them on every `pytest` invocation would make the suite unusable without credentials; `pytest -m integration` triggers them explicitly
- **Three target sites** — CafeF, VnEconomy, VietnamPlus; together they cover different DOM structures, URL patterns, and date formats across the main target sites
- **Functional criteria mapped directly from the intern plan** — each test corresponds to one acceptance criterion: crawl completion, depth correctness, deduplication, same-domain filter, date filter, and extraction accuracy
- **`fetch_page` smoke tests included** — three standalone fetch tests (VnEconomy home, VnEconomy stock-market section, invalid domain) verify the crawler layer independently of the agent loop

### Test Files Added

| File | Tests | What is covered |
|---|---|---|
| `test_integration.py` | 11 | Site smoke (CafeF, VnEconomy, VietnamPlus), depth correctness, dedup, same-domain filter, date filter, extraction accuracy, `fetch_page` contract |

---

## Module: `docs/architecture.md`

### Design Decisions

- **Two Mermaid diagrams** — one module-level diagram showing imports and dependencies; one data-flow diagram showing the observe → decide → act cycle; both follow the `flowchart TD` convention from the doc style guide
- **`AgentConfig` and `CrawlState` tables included** — field references otherwise only discoverable by reading the source; keeping them in the architecture doc makes them accessible without code navigation
- **Known limitations section** — limitations consolidated from weekly reports into one authoritative place

---

## Module: `src/agent.py` Updates

### Design Decisions

- **`max_chars` applied in `_agent_turn`, not on the stored `PageResult`** — the full markdown is preserved in `state.pages` and written to output; only the string passed to `render("user_turn.j2", ...)` is sliced; the stored record stays complete while Claude's input is controlled
- **`max_chars = 0` means no limit** — zero is the natural "off" default for a char cap; matches `int` type expectations in argparse
- **`css_selector` forwarded as `None` when empty** — `fetch_page` accepts `str | None`; converting the empty string avoids a behaviour difference between "flag not passed" and "flag passed empty"
- **Truncation logged at DEBUG** — truncation is expected behaviour when `max_chars` is set, not a warning; INFO output stays clean for users monitoring the crawl

### New `AgentConfig` Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `css_selector` | `str` | `""` | CSS selector forwarded to Crawl4AI to scope content extraction |
| `max_chars` | `int` | `0` | Max markdown characters sent to Claude per turn; 0 = no limit |

### Markdown Truncation in `_agent_turn`

```python
markdown = page.markdown
if config.max_chars > 0 and len(markdown) > config.max_chars:
    markdown = markdown[: config.max_chars]
```

- Applied before `render("user_turn.j2", ...)` — `page.markdown` is never mutated
- Logged at DEBUG with original and capped character counts

---

## Module: `src/logging_config.py` Updates

### Design Decisions

- **Standard fields ordered first, custom fields alphabetical** — `timestamp`, `level`, `logger`, `event` always appear in that position; remaining keys sorted; predictable field order makes log parsing and `jq` queries reliable
- **Implemented as a structlog processor** — `_order_log_fields` inserts into the processor chain and is independently testable without touching call sites

### Processor

```python
def _order_log_fields(
    logger: object, method_name: str, event_dict: dict[str, object]
) -> dict[str, object]
```

- Pops the four standard fields into a new dict in declaration order
- Copies remaining keys in `sorted()` order
- Returns the reordered dict for the next processor in the chain

---

## Module: `main.py` Updates

### New CLI Flags

| Flag | Default | Description |
|---|---|---|
| `--css-selector` | `""` | CSS selector to scope extraction, e.g. `"article.main-content"` |
| `--max-chars` | `0` | Truncate page markdown before sending to Claude; 0 = no limit |

---

## Smoke Test

**Unit test run (no network required):**

```bash
uv run pytest -m "not integration"
```

```text
189 passed, 11 deselected in 2.19s
```

**Integration test run (requires live internet + `ANTHROPIC_API_KEY`):**

```bash
uv run pytest tests/test_integration.py -v -s
```

```text
======================== 11 passed in 532.24s (0:08:52) ========================
```

Post-week verification note: the local Python 3.11.7 environment segfaulted while pytest
imported the native `readline` module during startup. The run used a temporary no-op import
shim to bypass that environment issue; the shim was removed immediately afterward.

**Rev 3 verification on 2026-06-10:**

```bash
uv run pytest -m "not integration" -q
uv run pytest tests/test_integration.py -m integration -v -s
uv run ruff check .
```

```text
212 passed, 11 deselected in 4.16s
======================== 11 passed in 582.35s (0:09:42) ========================
All checks passed!
```

The Rev 3 live run used the same temporary `readline` import shim because the local runtime
issue remains unresolved. The shim was outside the repository and removed after verification.

**Acceptance criteria:**

| Check | Expected | Actual |
|---|---|---|
| 189 unit tests pass | `pytest -m "not integration"` exits 0 | ✓ — 189 passed in 2.19 s |
| 11 live integration tests pass | Live sites and Anthropic API complete without assertion failures | ✓ — 11 passed in 532.24 s |
| Three target sites respond | CafeF, VnEconomy, and VietnamPlus crawls collect pages | ✓ |
| Crawler smoke tests pass | VnEconomy home, stock-market section, and invalid domain behave as expected | ✓ |
| `docs/architecture.md` exists | Module diagram, data flow, design decisions present | ✓ |
| `README.md` includes `--css-selector` and `--max-chars` | Flags appear in CLI reference table | ✓ |
| `css_selector` forwarded to `fetch_page` | Verified by `test_run_agent_passes_css_selector_to_fetch_page` | ✓ |
| JSON log fields in stable order | `timestamp, level, logger, event` always first | ✓ — verified by `test_logging_config.py` |
| `ruff check` passes | No lint errors | ✓ |
| Depth zero fetches only the seed | One real `fetch_page` call and one collected page | ✓ — Rev 3 live run |
| Dedup prevents duplicate network fetches | Every real `fetch_page` URL is unique | ✓ — Rev 3 live run |
| Date filtering is non-vacuous | At least one dated article is collected and in range | ✓ — Rev 3 live run |
| Four-field extraction succeeds | Title, publish date, author, and summary keys exist | ✓ — Rev 3 live run |
| Current unit suite passes | Non-integration suite exits 0 | ✓ — 212 passed in 4.16 s |

---

## Known Limitations

- **Async client cleanup emits non-fatal warnings** — repeated delayed `httpx.AsyncClient.aclose()` tasks raise `RuntimeError: Event loop is closed` between tests; all assertions still pass, but client lifecycle cleanup should be addressed in Week 7
- **Local Python `readline` import segfaults during pytest startup** — Python 3.11.7 from the current Anaconda-based environment crashes before collection; the live verification required a temporary import shim, so the Python installation should be repaired or replaced in Week 7
- **The agent can attempt extraction on a homepage before article classification settles** — the Rev 3 live run rejected one oversized homepage extraction after the model response truncated, while automatic article extraction still passed; tighten tool execution so extraction is accepted only for classified article pages in Week 7
- **`max_chars` is a character slice, not a token count** — a token-aware truncation would require a local tokeniser or an extra API call; deferred to Week 7
- **`css_selector` applies uniformly to every page** — seed, category, and article pages all receive the same selector; per-depth selector configuration is not yet supported
- **Date filter not applied to the seed page** — by design; seed always fetched for navigation

---

## Dependency Changes

No new dependencies added in Week 6.

---

## Week 7 Entry Criteria

- [x] Integration test suite written — 11 tests across CafeF, VnEconomy, VietnamPlus
- [x] `docs/architecture.md` written — module diagram, data flow, design decisions, field references
- [x] `README.md` updated — project structure, `--css-selector`, `--max-chars`
- [x] `--css-selector` wired end-to-end
- [x] `--max-chars` truncates Claude input without affecting stored output
- [x] All `print()` calls replaced with structured `structlog` events
- [x] 189 unit tests pass — `uv run pytest -m "not integration"` exits 0
- [x] Integration tests confirmed passing on live sites — 11 passed in 532.24 seconds
- [x] Rev 3 integration assertions verify real fetch depth, dedup, normalized domains, non-vacuous dates, and all four extraction fields
- [x] Current Gradio and schema-registry paths documented in `README.md` and `docs/architecture.md`
- [x] Rev 3 verification passes — 212 unit tests and 11 live integration tests
- [ ] Async HTTP client cleanup — close Anthropic/httpx clients before each pytest event loop ends
- [ ] Python runtime repair — replace or repair the environment whose native `readline` import segfaults
- [ ] Reject homepage extraction tool calls before sending oversized content to the extractor
- [ ] Per-page token breakdown — log `input_tokens` and `output_tokens` per page to identify budget hotspots
- [ ] Token-aware truncation — replace character-count slice with approximate token-boundary truncation
