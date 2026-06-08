# Implementation Spec — crawl-tool

**Purpose:** Function-level contracts for every module. Written before coding, used as context for the coding model, validated by tests.

**How to use:**
- Before implementing a module, read its section here and share it as context with Claude
- After implementing, write unit tests that verify each function's contract
- Update this file if a signature changes during implementation

**Testing scope:**
- Tests cover **public functions only** — the main functions other modules call
- Private helpers (prefixed `_`) are not tested directly — covered indirectly through public function tests

---

## Week 1 — Repo Skeleton

No functions implemented. Week 1 deliverables are configuration files only.

**Files created:**
- `pyproject.toml` — uv-managed deps, Ruff config (line-length 100, rules E/F/I/UP/B/SIM)
- `.gitignore`
- `src/__init__.py`
- Empty stubs: `src/crawler.py`, `src/output.py`, `src/agent.py`, `src/extractor.py`, `src/date_filter.py`, `src/prompts.py`
- Empty dirs: `tests/`, `docs/`, `prompts/`

---

## Week 2 — `src/crawler.py` + `src/output.py`

### `src/models/page.py`

#### `PageResult` (Pydantic BaseModel)

- Shared domain type used by every module — import via `from src.models import PageResult`
- Defined in `src/models/` so it is decoupled from the fetch implementation; never import Crawl4AI outside `crawler.py`

| Field | Type | Description |
|---|---|---|
| `url` | `str` | Original requested URL |
| `final_url` | `str` | URL after redirects |
| `status_code` | `int \| None` | HTTP status code |
| `title` | `str \| None` | From `metadata["title"]` or `og:title` |
| `markdown` | `str` | Filtered content (primary Claude input) |
| `raw_markdown` | `str \| None` | Unfiltered markdown — excluded from output |
| `html` | `str \| None` | Raw HTML — excluded from output, debug only |
| `links_internal` | `list[str]` | Same-domain links as plain URL strings |
| `links_external` | `list[str]` | Off-domain links as plain URL strings |
| `metadata` | `dict` | All page metadata (OG tags, JSON-LD, etc.) |
| `fetch_time` | `float \| None` | Fetch duration in seconds |
| `headers` | `dict` | HTTP response headers — used by `detect_page_date` for `Last-Modified` |
| `success` | `bool` | False if fetch failed for any reason |
| `error` | `str \| None` | Error message when success=False |

### `src/crawler.py`

#### `fetch_page`

```python
async def fetch_page(
    url: str,
    css_selector: str | None = None,
    *,
    article_body: bool = True,
) -> PageResult
```

**Arguments:**

| Argument | Type | Description |
|---|---|---|
| `url` | `str` | Absolute URL to fetch. This is stored as `PageResult.url` even if redirects occur. |
| `css_selector` | `str \| None` | Optional CSS selector used to limit extraction to part of the page. When `None`, Crawl4AI extracts from the full page. |
| `article_body` | `bool` | When `True`, article-looking URLs use known or generic article-body targets. When `False`, fetches the full page. |

- Fetches one web page through Crawl4AI using headless Chromium
- Returns a normalized `PageResult` containing markdown, metadata, links, and fetch status
- Uses boilerplate-pruned markdown when Crawl4AI provides it; otherwise uses raw markdown
- When `css_selector` is provided, hard-scopes content extraction to matching elements
- When `article_body=True` and `css_selector=None`, detects article-looking URLs and passes Crawl4AI `target_elements` so markdown focuses on title, date, author, summary, and article body while metadata and links remain available
- Uses known site targets before generic targets, including CafeF/TuoiTre/VnEconomy article selectors and domain-specific targets for Baodautu and VietnamPlus
- Retries a scoped article fetch as a full-page fetch when scoped markdown is unusable, including whitespace-only or very short markdown
- Parses explicit bylines from full HTML into `PageResult.metadata["byline_author"]` when an article page exposes an author outside the scoped markdown
- Converts crawl errors and unexpected exceptions into `PageResult(success=False, error=...)`
- Treats HTTP status codes `>= 400` as failures even if Crawl4AI reports `success=True`
- Crawl4AI config: `cache_mode=BYPASS`, `check_robots_txt=True`, `remove_forms=True`, `remove_overlay_elements=True`, `PruningContentFilter(threshold=0.6)`, markdown links ignored

**Test cases:**
- `fetch_page("https://cafef.vn")` → `success=True`, `status_code=200`, `markdown` non-empty, `links_internal` non-empty
- `fetch_page("https://cafef.vn")` → `title` is not None
- `fetch_page("https://invalid-url-that-does-not-exist.xyz")` → `success=False`, `error` is not None, does not raise
- `fetch_page("https://cafef.vn", css_selector=".main-content")` → returns `PageResult` without raising
- `fetch_page("https://cafef.vn/bai-viet-123456789.chn")` → uses `target_elements=[".detail-content"]`, not `css_selector`
- `fetch_page("https://baodautu.vn/...-d611681.html")` → uses domain-specific target `.col630.ml-auto.mb40`
- `fetch_page("https://www.vietnamplus.vn/...-post1114632.vnp")` → uses title/sapo/meta/body targets and preserves byline author
- Scoped fetch returning `"\n"` or empty markdown → retries full-page fetch
- Article HTML with `<p class="author-detail">By Ngan Ha</p>` → `metadata.byline_author == "Ngan Ha"`

**Private helpers:**
- `_extract_links` — flattens Crawl4AI link dict to plain URL lists
- `article_selector_for_url` — returns known site article-body selector for matching URLs
- `looks_like_article_url` — classifies known, domain-specific, and generic article URL patterns
- `article_target_elements_for_url` — returns known, domain-specific, or generic article target selectors
- `_extract_byline_author` — extracts explicit author bylines from full page HTML
- `_clean_byline` — normalizes byline text and removes email/date suffixes

---

### `src/output.py`

#### `write_results`

```python
def write_results(
    pages: list[PageResult],
    path: str,
    fmt: str = "json",
    run_meta: dict | None = None,
) -> None
```

**Arguments:**

| Argument | Type | Description |
|---|---|---|
| `pages` | `list[PageResult]` | Page results collected during the crawl. Each page is converted to a serializable record before writing. |
| `path` | `str` | Destination file path for the output file. Parent directories must already exist. |
| `fmt` | `str` | Output format selector. Supported values are `"json"` and `"jsonl"`. |
| `run_meta` | `dict \| None` | Optional crawl-level metadata such as seed URL, goal, token counts, and finish reason. Used only for JSON output. |

- Public output entry point used by the CLI
- Writes crawl results in either envelope JSON or newline-delimited JSON format
- Uses `write_json` when `fmt == "json"` and `write_jsonl` when `fmt == "jsonl"`
- Passes `run_meta` into JSON output metadata; JSONL output intentionally has no metadata envelope

**Test cases:**
- `write_results(pages, path, fmt="json")` → file is valid JSON, contains `meta` and `pages` keys
- `write_results(pages, path, fmt="jsonl")` → file has one JSON object per line, no envelope
- `write_results(pages, path, fmt="json", run_meta={"goal": "test"})` → `meta.goal == "test"` in output
- `write_results(pages, path, fmt="json")` → no `html` or `raw_markdown` fields in any page record
- `write_results(pages, path, fmt="json")` → Vietnamese characters preserved (not escaped as `\uXXXX`)
- `write_results([], path, fmt="json")` → `meta.total_pages == 0`, `pages == []`

#### `write_json`

```python
def write_json(pages: list[PageResult], path: str, run_meta: dict | None = None) -> None
```

**Arguments:**

| Argument | Type | Description |
|---|---|---|
| `pages` | `list[PageResult]` | Page results to include in the `pages` array. |
| `path` | `str` | Destination path for the JSON file. Existing files may be overwritten. |
| `run_meta` | `dict \| None` | Additional fields merged into the top-level `meta` object after the default generated fields. |

- Writes a single JSON document with top-level `meta` and `pages` keys
- Builds `meta` from generated timestamp, page counts, success/failure counts, and optional `run_meta`
- Serializes each `PageResult` after removing large debug-only fields: `html` and `raw_markdown`
- Writes UTF-8 JSON with `ensure_ascii=False` so Vietnamese text remains readable

**Test cases:**
- Output file contains `meta.generated_at`, `meta.total_pages`, `meta.successful`, `meta.failed`
- `successful` + `failed` == `total_pages`
- `run_meta` fields merged into `meta` block

#### `write_jsonl`

```python
def write_jsonl(pages: list[PageResult], path: str) -> None
```

**Arguments:**

| Argument | Type | Description |
|---|---|---|
| `pages` | `list[PageResult]` | Page results to write, one serialized record per line. |
| `path` | `str` | Destination path for the JSONL file. Existing files may be overwritten. |

- Writes one serialized page record per line
- Does not include a top-level `meta` block, because each line must be independently parseable
- Applies the same page cleanup as `write_json`: excludes `html` and `raw_markdown`
- Intended for large crawls where streaming or line-by-line processing is useful

**Test cases:**
- Line count equals number of pages
- Each line is valid JSON and parses without error

**Private helpers:** `_page_record` — converts `PageResult` to dict, strips `html` and `raw_markdown`

---

## Week 3 — `src/prompts.py` + `src/agent.py`

### `src/prompts.py`

#### `render`

```python
def render(template_name: str, **context: object) -> str
```

**Arguments:**

| Argument | Type | Description |
|---|---|---|
| `template_name` | `str` | Filename of the template inside `prompts/`, such as `"system.j2"` or `"user_turn.j2"`. |
| `**context` | `object` | Template variables passed to Jinja2. Keys must match the variables referenced by the template. |

- Loads a prompt template from the repository `prompts/` directory
- Renders the template with the keyword arguments passed in `context`
- Uses strict variable handling: missing template variables raise `jinja2.UndefinedError`
- Lets `jinja2.TemplateNotFound` propagate when the requested template file does not exist
- Jinja2 config: `StrictUndefined`, `trim_blocks=True`, `lstrip_blocks=True`

**Test cases:**
- `render("system.j2", goal=..., max_depth=..., max_pages=..., same_domain=...)` → returns non-empty string containing the goal text
- `render("user_turn.j2", ...)` with all required variables → returns non-empty string
- `render("system.j2")` with a missing variable → raises `jinja2.UndefinedError`
- `render("nonexistent.j2", ...)` → raises `jinja2.TemplateNotFound`

---

### `src/agent.py`

#### `AgentConfig` (Pydantic BaseModel)

| Field | Type | Default | Description |
|---|---|---|---|
| `goal` | `str` | `""` | Natural-language crawl goal |
| `max_depth` | `int` | `1` | Hard depth ceiling |
| `max_pages` | `int` | `100` | Hard page cap |
| `token_budget` | `int` | `500_000` | Total input + output token cap |
| `same_domain` | `bool` | `True` | Restrict crawl to seed domain |
| `include_patterns` | `list[str]` | `[]` | Glob patterns URLs must match |
| `exclude_patterns` | `list[str]` | `[]` | Glob patterns that block a URL |
| `model` | `str` | `"claude-haiku-4-5-20251001"` | Anthropic model ID |

Week 4 adds `extract_prompt` and `extract_schema`. Week 5 adds `date_filter` and `include_undated` — see those sections.

#### `CrawlState` (Pydantic BaseModel)

| Field | Type | Description |
|---|---|---|
| `frontier` | `list[tuple[str, int]]` | FIFO queue of `(url, depth)` — BFS order |
| `visited` | `set[str]` | Canonical URLs already fetched or skipped |
| `pages` | `list[PageResult]` | Successfully fetched pages |
| `total_input_tokens` | `int` | Cumulative input tokens across all Claude calls |
| `total_output_tokens` | `int` | Cumulative output tokens |
| `finished` | `bool` | Set True when agent calls `finish` tool |
| `finish_reason` | `str` | Agent's stated reason for finishing |
| `stop_reason` | `str` | Machine-readable stop: `"agent_finish"`, `"max_pages"`, `"token_budget"`, `"frontier_empty"` |
| `article_pages` | `list[str]` | URLs classified as article pages — used to enforce min-article goals |
| `frontier_at_finish` | `list[str]` | Frontier URLs remaining when crawl stopped — preserved in output metadata |

| Property | Returns | Description |
|---|---|---|
| `tokens_used` | `int` | `total_input_tokens + total_output_tokens` |

#### `run_agent`

```python
async def run_agent(seed_url: str, config: AgentConfig) -> CrawlState
```

**Arguments:**

| Argument | Type | Description |
|---|---|---|
| `seed_url` | `str` | Starting URL for the crawl. It is canonicalized and added to the frontier at depth 0. |
| `config` | `AgentConfig` | Crawl goal, hard limits, URL guardrails, token budget, and model selection for this run. |

- Main crawl entry point
- Starts a new `CrawlState` with the seed URL queued at depth 0
- Repeatedly fetches the next frontier URL, records successful pages, and asks Claude which links to follow
- Applies hard stop conditions before each fetch: empty frontier, agent finish signal, `max_pages`, and `token_budget`
- Reuses one rendered system prompt across turns and sends it with Anthropic ephemeral cache control
- Returns the final `CrawlState`, including visited URLs, collected pages, finish reason, and token totals

**Test cases:**
- `run_agent(url, config)` → returns `CrawlState` with `pages` non-empty and `visited` non-empty
- `run_agent(url, config(max_pages=1))` → `len(state.pages) <= 1`
- `run_agent(url, config(max_depth=0))` → no depth-1 URLs in `visited`
- `run_agent(url, config(same_domain=True))` → all URLs in `visited` share the seed domain
- `run_agent(url, config(token_budget=1))` → loop exits before making a second Claude call
- `run_agent(url, config)` → `state.tokens_used == state.total_input_tokens + state.total_output_tokens`
- `run_agent("https://invalid.xyz", config)` → returns `CrawlState` with `pages == []`, does not raise

**Claude tools defined (TOOLS constant):**

| Tool | Required inputs | Optional inputs | Effect |
|---|---|---|---|
| `add_to_frontier` | `url: str` | `reason: str` | Adds a relevant URL to the crawl queue if guardrails allow it |
| `mark_visited` | `url: str` | — | Marks a URL as already handled so it will not be fetched later |
| `finish` | `reason: str` | — | Stops the crawl and records the agent's completion reason |

**Private helpers:**
- `_agent_turn` — sends one fetched page to Claude and processes any tool calls Claude requests
- `_execute_tool` — applies one tool call to crawl state and returns a short result message for Claude
- `_allowed` — returns whether a URL passes same-domain and include/exclude pattern guardrails
- `_canonical` — removes URL fragments before deduplication
- `_same_domain` — checks whether two URLs have the same network location
- `_parse_min_articles` — extracts numeric minimum article count from the goal string (e.g. `"at least 3 articles"` → `3`)
- `_is_article_page` — returns True when page metadata (`article:published_time`) or known/generic article URL patterns indicate an article
- `_is_current_page_link` — rejects agent-added URLs that were not extracted from the current page
- `_article_candidate_links` — surfaces internal links that match article URL patterns even when the full internal-link list is long

---

## Week 4 — `src/extractor.py` + agent tool update

### `src/extractor.py`

#### `extract`

```python
async def extract(
    page: PageResult,
    prompt: str,
    schema: dict | None = None,
) -> dict
```

**Arguments:**

| Argument | Type | Description |
|---|---|---|
| `page` | `PageResult` | Fetched page to extract from. `page.markdown` is the primary extraction input. |
| `prompt` | `str` | User's natural-language instruction describing which fields to extract. |
| `schema` | `dict \| None` | JSON Schema used to validate Claude's output. When `None`, `infer_schema(prompt)` is called first. |

- Extracts structured data from one fetched page
- Sends page content, user extraction prompt, and JSON Schema to Claude using `prompts/extract.j2`
- Prepends title, detected publish date, explicit byline author, and source when available so scoped article-body markdown can still produce complete structured fields
- Uses `detect_page_date(page)` as the date source before rendering extraction context
- If no schema is supplied, first derives one from the prompt with `infer_schema`
- Parses Claude's response as JSON and validates it with `jsonschema`
- Returns the validated extraction result on success
- On parse or validation failure, returns an error dict containing the message and raw Claude output; extraction failure does not stop the crawl

**Test cases:**
- `extract(page, "extract title and date")` → returns dict with non-empty keys
- `extract(page_with_metadata_byline, "extract author")` → rendered prompt includes `Author: ...`
- `extract(page_with_site_name, "extract source")` → rendered prompt includes `Source: ...`
- `extract(page, "extract title", schema={"type": "object", "properties": {"title": {"type": "string"}}})` → output passes schema validation
- `extract(page, "extract title", schema={"type": "object", "required": ["missing_field"]})` → returns dict with `"error"` key, does not raise
- `extract(page_with_empty_markdown, "extract title")` → returns dict with `"error"` key, does not raise

#### `infer_schema`

```python
async def infer_schema(prompt: str) -> dict
```

**Arguments:**

| Argument | Type | Description |
|---|---|---|
| `prompt` | `str` | Natural-language extraction request to convert into a JSON Schema. |

- Converts a natural-language extraction request into a JSON Schema
- Sends the user prompt to Claude using `prompts/infer_schema.j2`
- Parses Claude's response and returns it as a JSON Schema dictionary
- Used only when `extract()` is called without an explicit schema

**Test cases:**
- `infer_schema("extract article title and publish date")` → returns dict with `"type": "object"` and `"properties"` key
- `infer_schema("extract price and availability")` → returned schema has `"price"` or `"availability"` in properties

**Private helpers:**
- `_validate` — runs `jsonschema.validate`, returns `(True, "")` on pass or `(False, error_message)` on fail

**Prompt templates added:**
- `prompts/extract.j2` — user turn for structured extraction; variables: `markdown`, `prompt`, `schema_json`
- `prompts/infer_schema.j2` — user turn for schema inference; variable: `prompt`

---

### `src/agent.py` updates (Week 4)

- New tool `extract` added to `TOOLS` constant
- `_execute_tool` updated to handle `extract` — calls `src/extractor.extract()`, attaches result to `page` record
- `system.j2` updated to include `extract_prompt` variable when provided
- Per-page extraction errors stored in page record, do not abort the loop
- `AgentConfig` gains `extract_prompt: str = ""` and `extract_schema: dict | None = None`
- `CrawlState` gains `stop_reason`, `article_pages`, `frontier_at_finish` to support the finish guard and output metadata
- New private helpers: `_parse_min_articles` (goal → min count), `_is_article_page` (URL/metadata classifier)
- `finish` tool guard added to `_execute_tool`: rejected when reachable URLs remain in frontier or min-article target not met

**New tool:**

| Tool | Required inputs | Optional inputs | Effect |
|---|---|---|---|
| `extract` | `prompt: str` | `schema: dict` | Extracts structured fields from the current page |

---

### `main.py` updates (Week 4)

- `--extract-prompt` flag wired into `AgentConfig` and injected into system prompt
- `--extract-schema` flag loads JSON Schema from file path, passed to `extract()`

---

## Week 5 — `src/date_filter.py` + retry policy

### `src/date_filter.py`

#### `parse_date_filter`

```python
def parse_date_filter(prompt: str, today: date | None = None) -> tuple[date, date]
```

**Arguments:**

| Argument | Type | Description |
|---|---|---|
| `prompt` | `str` | User-provided date expression, such as `"last 7 days"` or `"since 2026-01-01"`. |
| `today` | `date \| None` | Override for the current date — used in tests to fix the reference point. |

- Converts a user-provided date filter into an inclusive `(from_date, to_date)` range
- Supported patterns: `"last N days/weeks/months"`, `"last week/month/year"`, `"this week/month/year"`, `"today"`, `"yesterday"`, `"since <date>"`, `"between <date> and <date>"`, `"<date>"`
- A `<date>` token is parsed ISO-first (`YYYY-MM-DD`) then via a `dateparser` fallback, so natural-language dates (`"June 1st"`, `"1 June 2026"`) are accepted as well as ISO
- `"since YYYY-MM-DD"` treats today as the upper bound — returns `(parsed_date, today)`
- Raises `ValueError` for empty, ambiguous, or unparseable input instead of guessing

**Test cases:**
- `parse_date_filter("last 7 days")` → `to_date == today`, `from_date == today - 7 days`
- `parse_date_filter("since 2026-01-01")` → `from_date == date(2026, 1, 1)`, `to_date == today`
- `parse_date_filter("this month")` → `from_date == first day of current month`, `to_date == today`
- `parse_date_filter("sometime recently")` → raises `ValueError`
- `parse_date_filter("")` → raises `ValueError`

#### `detect_page_date`

```python
def detect_page_date(page: PageResult) -> date | None
```

**Arguments:**

| Argument | Type | Description |
|---|---|---|
| `page` | `PageResult` | Fetched page whose metadata and headers are inspected for publication or update dates. |

- Finds the best available publication or update date for a fetched page
- Checks date signals in priority order:
  1. `<meta>` tags — `article:published_time`, `og:updated_time`
  2. JSON-LD — `datePublished`, `dateModified`
  3. HTTP `Last-Modified` header via `page.headers` (lowest priority)
  4. Vietnamese news URL pattern — `188YYMMDD…` embedded in the URL path
- Returns a `date` when a valid signal is found
- Returns `None` when the page has no usable date signal or all date strings are malformed

**Test cases:**
- Page with `article:published_time` meta tag → returns correct date
- Page with JSON-LD `datePublished` → returns correct date
- Page with only `Last-Modified` header → returns correct date
- Page with Vietnamese URL pattern (`188260603...`) → returns correct date
- Page with no date signals → returns `None`
- Page with malformed date string in meta → returns `None`, does not raise

#### `is_in_range`

```python
def is_in_range(
    page_date: date | None,
    from_date: date,
    to_date: date,
    include_undated: bool = False,
) -> bool
```

**Arguments:**

| Argument | Type | Description |
|---|---|---|
| `page_date` | `date \| None` | Date detected for the page. `None` means no usable date was found. |
| `from_date` | `date` | Inclusive lower bound of the accepted date range. |
| `to_date` | `date` | Inclusive upper bound of the accepted date range. |
| `include_undated` | `bool` | Whether to keep pages when `page_date` is `None`. |

- Evaluates whether a detected page date should be included in a crawl result
- Treats `from_date` and `to_date` as inclusive boundaries
- Returns `include_undated` when no page date is available
- Used by the agent loop to keep pages inside the requested date range and drop pages outside it

**Test cases:**
- `is_in_range(date(2026, 5, 1), date(2026, 4, 1), date(2026, 5, 31))` → `True`
- `is_in_range(date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 31))` → `False`
- `is_in_range(None, ..., ..., include_undated=True)` → `True`
- `is_in_range(None, ..., ..., include_undated=False)` → `False`
- `is_in_range(date(2026, 5, 1), date(2026, 5, 1), date(2026, 5, 1))` → `True` (boundary inclusive)

---

### `src/agent.py` updates (Week 5)

`AgentConfig` gains two fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `date_filter` | `str` | `""` | Natural-language date filter passed to `parse_date_filter` |
| `include_undated` | `bool` | `True` | Whether to keep pages with no detectable date |

### `src/crawler.py` updates (Week 5) — retry policy

- `fetch_page` updated with exponential backoff: max 3 retries on `5xx` or timeout
- Reads actual `Retry-After` header value on `429` responses (falls back to 60s)
- Each retry logged at `WARNING` level with attempt number and reason
- After 3 failed retries returns `PageResult(success=False, error=...)` — still never raises
- `PageResult` gains `fetch_time: float | None` and `headers: dict` fields (added alongside retry policy)

---

### Structured logging (Week 5)

- Per-page log line: `url | status_code | depth | fetch_time_ms`
- End-of-crawl summary logged via `src/output.py`: total pages, failed pages, total time, tokens used
- Log level: `INFO` for normal flow, `WARNING` for retries and dropped pages

---

## Week 6 — Tests + Docs + Handover

### Test files

| File | Covers |
|---|---|
| `tests/test_output.py` | `write_results`, `write_json`, `write_jsonl` |
| `tests/test_prompts.py` | `render` |
| `tests/test_extractor.py` | `extract`, `infer_schema` |
| `tests/test_date_filter.py` | `parse_date_filter`, `detect_page_date`, `is_in_range` |
| `tests/test_agent.py` | `run_agent` (mocked Claude + fetch) |
| `tests/test_crawler.py` | `fetch_page` (live integration, marked slow) |
| `tests/test_integration.py` | End-to-end on 3 real Vietnamese economy sites |

### Test strategy

- **Unit tests** — mock Claude API calls and `fetch_page`; test logic only, no live HTTP
- **Integration tests** — real HTTP, real Claude API; marked with `@pytest.mark.integration` and run separately
- `fetch_page` tests hit live sites — marked `@pytest.mark.slow`; excluded from default `pytest` run

### Docs deliverables

| File | Description |
|---|---|
| `docs/architecture.md` | Module diagram, data flow, key design decisions, known limitations |
| `README.md` | Installation, quick start, CLI reference, example usage |
