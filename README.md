# crawl-tool

An agent-driven crawler with CLI and Gradio interfaces that uses Claude to navigate Vietnamese economy and finance news sites and extract structured data for downstream analysis.

Claude drives every crawl decision — which links to follow, what to extract, when to stop. Hard guardrails (depth, domain, robots.txt, token budget) are enforced in code and cannot be overridden by the agent.

---

## Project Structure

```
crawl-tool/
├── app.py                   # Gradio interface entry point
├── main.py                  # CLI entry point
├── pyproject.toml           # Dependencies and Ruff config
├── prompts/                 # Jinja2 prompt templates
│   ├── system.j2
│   ├── user_turn.j2
│   ├── extract.j2
│   └── infer_schema.j2
├── src/
│   ├── models/page.py       # PageResult — shared domain type
│   ├── agent.py             # LLM agent loop — observe, decide, act
│   ├── crawler.py           # Crawl4AI wrapper — fetch_page with retry
│   ├── extractor.py         # Structured extraction via Claude
│   ├── schema_registry.py   # Deterministic schemas for known extraction intents
│   ├── date_filter.py       # NL date parsing and page date detection
│   ├── logging_config.py    # structlog configuration
│   ├── prompts.py           # Jinja2 template loader
│   ├── ui.py                # Gradio controls, validation, preview and downloads
│   └── output.py            # JSON / JSONL serialization
├── tests/
│   ├── test_integration.py  # End-to-end tests (run with: pytest -m integration)
│   └── ...                  # Unit tests (run with: pytest)
└── docs/
    ├── architecture.md      # Module diagram, data flow, design decisions
    ├── crawl-tool-intern-plan.md
    ├── implementation_spec.md
    ├── standards/
    └── reports/
```

---

## Features

- Goal-directed crawling — describe what you want in plain language
- Structured extraction — extract fields into JSON Schema via natural language prompt
- Registered schemas for known financial extraction intents, with LLM inference fallback
- CLI and browser-based Gradio workflows over the same crawl engine
- Depth and page budget controls
- Same-domain restriction and URL pattern filters
- Date filtering — `"last 7 days"`, `"since 2026-01-01"`, etc.
- JSON and JSONL output with crawl metadata block
- robots.txt compliance by default

---

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — package manager
- An Anthropic API key with available credits

---

## Installation

```bash
git clone <repo-url>
cd crawl-tool
uv sync
uv run playwright install chromium
```

Set your API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Or add it to a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Then load it before running:

```bash
source .env
```

---

## Quick Start

Crawl CafeF for the latest economy news:

```bash
uv run python main.py https://cafef.vn \
  --goal "fetch the full content of the latest economy news articles" \
  --max-depth 1 \
  --max-pages 10 \
  --output results.json
```

Extract structured fields from each page:

```bash
uv run python main.py https://cafef.vn \
  --goal "collect economy news articles" \
  --extract-prompt "extract article title, publish date, and key financial figures mentioned" \
  --max-depth 1 \
  --max-pages 10 \
  --output results.json
```

Launch the browser interface:

```bash
uv run python app.py
```

The Gradio UI exposes crawl goals, extraction prompts, optional JSON Schema input,
date and URL filters, crawl limits, JSON preview, and downloadable JSON or JSONL output.

When no schema is supplied, the agent first checks the schema registry for a recognized
intent. Unmatched prompts use Claude schema inference. A schema supplied through the CLI
or UI always takes precedence.

---

## CLI Reference

```
uv run python main.py <url> [options]
```

### Arguments

| Argument | Description |
|---|---|
| `url` | Seed URL to start crawling from |

### Options

| Flag | Default | Description |
|---|---|---|
| `--goal` | `""` | Natural-language crawl goal |
| `--extract-prompt` | `""` | What to extract from each page |
| `--extract-schema` | `""` | Path to a JSON Schema file for extraction output |
| `--max-depth` | `1` | Maximum crawl depth (seed = depth 0) |
| `--max-pages` | `100` | Maximum pages to fetch |
| `--token-budget` | `500000` | Total Claude token cap across the crawl |
| `--date-filter` | `""` | Natural-language date range, e.g. `"last 7 days"` or `"articles since June 1st"` |
| `--include-undated` | off | Include pages with no detectable publish date |
| `--css-selector` | `""` | CSS selector to scope content extraction, e.g. `"article.main-content"` |
| `--max-chars` | `0` | Truncate page markdown to this many chars before sending to Claude; 0 = no limit |
| `--same-domain` | on | Restrict crawl to the seed domain |
| `--no-same-domain` | — | Allow following off-domain links |
| `--include-pattern` | `[]` | Glob pattern URLs must match (repeatable) |
| `--exclude-pattern` | `[]` | Glob pattern that blocks a URL (repeatable) |
| `--output` | `output.json` | Output file path |
| `--format` | `json` | Output format: `json` or `jsonl` |
| `--verbose` | off | Enable INFO logging |

---

## Output Format

### JSON (default)

```json
{
  "meta": {
    "generated_at": "2026-05-29T05:18:50Z",
    "seed_url": "https://cafef.vn",
    "goal": "collect economy news articles",
    "max_depth": 1,
    "max_pages": 10,
    "pages_collected": 8,
    "urls_visited": 12,
    "total_input_tokens": 42100,
    "total_output_tokens": 3800,
    "finish_reason": "goal satisfied"
  },
  "pages": [
    {
      "url": "https://cafef.vn/article.chn",
      "final_url": "https://cafef.vn/article.chn",
      "status_code": 200,
      "title": "Article title",
      "markdown": "...",
      "links_internal": ["..."],
      "links_external": ["..."],
      "metadata": {},
      "success": true,
      "error": null
    }
  ]
}
```

### JSONL

One JSON object per line — same fields as each `pages[n]` entry above, no envelope. Use with `--format jsonl` for large crawls.

---

## Examples

**Crawl with URL pattern filter:**
```bash
uv run python main.py https://cafef.vn \
  --goal "collect stock market news" \
  --include-pattern "*/chung-khoan/*" \
  --exclude-pattern "*/tag/*" \
  --max-depth 2 --max-pages 50
```

**Date-filtered crawl:**
```bash
uv run python main.py https://vneconomy.vn \
  --goal "collect economy news from this week" \
  --date-filter "last 7 days" \
  --max-depth 1 --max-pages 30
```

**JSONL output for large crawl:**
```bash
uv run python main.py https://cafef.vn \
  --goal "collect all available economy articles" \
  --max-depth 2 --max-pages 500 \
  --format jsonl --output results.jsonl
```

---

## Development

Run linter:
```bash
uv run ruff check .
uv run ruff format .
```

Run tests:
```bash
uv run pytest
```

Run integration tests (requires live internet + API key):
```bash
uv run pytest -m integration
```

---

## Compliance

- robots.txt honored by default — disable with `--no-respect-robots` (requires explicit opt-in)
- Headless Chromium — no bypassing of paywalls or DRM
- Credentials never written to logs or output files
