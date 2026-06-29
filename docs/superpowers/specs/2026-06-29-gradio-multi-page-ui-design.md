# Gradio Multi-Page UI Design

**Date:** 2026-06-29
**Status:** Approved

---

## Overview

Restructure the Gradio UI from a single 955-line page into three focused pages behind a sidebar navigation: **Quick Crawl** (one-prompt NL flow), **Advanced Crawl** (current full form), and **Storage** (MinIO stats + DuckDB query). The engine gains a `POST /parse` endpoint and two new storage endpoints.

---

## Architecture

### File layout

```
src/crawl_tool/
├── engine/
│   ├── storage.py          ← add list_results(), delete_result(), get_stats()
│   └── service.py          ← add POST /parse, GET /storage, DELETE /storage/{job_id}
└── gradio/
    ├── app.py              ← compose sidebar + mount all three pages
    ├── client.py           ← add parse_prompt(), list_results(), delete_result(), get_stats()
    ├── ui_styles.py        ← extract CUSTOM_CSS and _RESULT_JS from ui.py
    ├── ui_shared.py        ← extract run_crawl(), _build_request(), _validate_url(), _sample_tags()
    ├── ui_results.py       ← unchanged
    ├── ui_advanced_crawl.py  ← refactored from ui.py (no History tab)
    ├── ui_quick_crawl.py   ← new
    └── ui_storage.py       ← new
```

`ui.py` is deleted. Its contents are distributed across `ui_styles.py`, `ui_shared.py`, and `ui_advanced_crawl.py`.

### Module responsibilities

| Module | Responsibility |
|---|---|
| `ui_styles.py` | `CUSTOM_CSS`, `_RESULT_JS` constants |
| `ui_shared.py` | `run_crawl()`, `_build_request()`, `_validate_url()`, `_sample_tags()` |
| `ui_advanced_crawl.py` | `build_advanced_crawl_page()` — full form, results tabs |
| `ui_quick_crawl.py` | `build_quick_crawl_page()` — NL prompt → parse → edit → run |
| `ui_storage.py` | `build_storage_page()` — stats, object list, DuckDB query |
| `app.py` | `build_demo()` — sidebar nav, wires pages together |

---

## Engine Changes

### `POST /parse`

```
Body:   {"prompt": "get finance news from cafef.vn last 7 days, extract title and summary"}
200:    {"seed_url": "...", "goal": "...", "date_filter": "...", "extract_prompt": "...", ...}
422:    {"detail": "..."} — PromptParseError (no URL found, JSON error, etc.)
```

Thin wrapper around the existing `parse_crawl_prompt()`. No crawl is started. Fields not inferred by Claude are omitted from the response.

### `GET /storage`

```
200: {
  "total_files": 12,
  "total_size_bytes": 409600,
  "last_modified": "2026-06-29T10:00:00Z",
  "objects": [
    {"job_id": "abc123", "size_bytes": 34000, "last_modified": "2026-06-29T10:00:00Z"},
    ...
  ]
}
503: storage not configured
```

Calls `list_results()` from `storage.py`, which uses `client.list_objects(bucket)` and aggregates size and recency metadata.

### `DELETE /storage/{job_id}`

```
204: deleted successfully
404: result not found
503: storage not configured
```

Calls `delete_result(job_id, settings)` from `storage.py`, which calls `client.remove_object(bucket, "crawl-{job_id}.json")`.

### `storage.py` new functions

```python
def list_results(settings: StorageSettings) -> list[dict]
    # returns [{job_id, size_bytes, last_modified}, ...]

def delete_result(job_id: str, settings: StorageSettings) -> None
    # raises S3Error if not found

def get_stats(settings: StorageSettings) -> dict
    # returns {total_files, total_size_bytes, last_modified}
    # derived from list_results()
```

All three are synchronous and wrapped in `asyncio.to_thread` at the service layer.

---

## Gradio Client (`client.py`) Changes

```python
async def parse_prompt(prompt: str) -> dict
    # POST /parse → returns parsed fields dict
    # raises httpx.HTTPStatusError on 422

async def get_storage_overview() -> dict
    # GET /storage → returns stats + object list

async def delete_result(job_id: str) -> None
    # DELETE /storage/{job_id}
```

---

## Page Designs

### Sidebar navigation

`app.py` builds one `gr.Blocks` with a top-level `gr.Row`:

- **Left column** (scale=1): vertical `gr.Radio` with choices `["Quick Crawl", "Advanced Crawl", "Storage"]`, styled via CSS to hide the radio circle and highlight the selected item with the accent color. App title above the nav.
- **Right column** (scale=4): three `gr.Column` groups. Only the active one has `visible=True`. Default: Quick Crawl.

`nav.change()` returns `gr.update(visible=...)` for all three columns — one visible, two hidden.

---

### Quick Crawl page (`ui_quick_crawl.py`)

**Phase 1 — Prompt input**

- `gr.Textbox` (5 lines): placeholder "Describe your crawl — include the site, what you want, and any date range or extraction needs"
- Sample prompt tags (same `_sample_tags` pattern): e.g. "Finance news from cafef.vn last 7 days", "Stock articles from vietnamnet.vn this week"
- "Parse" button (primary) → calls `client.parse_prompt()` → on success: hides Phase 1, shows Phase 2; on error: shows inline `gr.Markdown` error

**Phase 2 — Editable preview + run**

Shown after successful parse. Fields pre-filled with Claude's inference, all editable:

| Component | Gradio type | Source |
|---|---|---|
| Seed URL | `gr.Textbox` | `parsed["seed_url"]` |
| Goal | `gr.Textbox` | `parsed.get("goal", "")` |
| Date filter | `gr.Textbox` | `parsed.get("date_filter", "")` |
| Extraction prompt | `gr.Textbox` | `parsed.get("extract_prompt", "")` |
| Max depth | `gr.Slider` (0–5) | `parsed.get("max_depth", 1)` |
| Max pages | `gr.Slider` (1–100) | `parsed.get("max_pages", 10)` |

- Read-only chip strip: which fields Claude inferred vs. which are defaults (e.g. `seed_url ✓ goal ✓ date_filter ✓ extract_prompt — max_depth default`)
- "Run crawl" button → calls `run_crawl()` from `ui_shared.py` with the (possibly edited) field values
- "← Edit prompt" link → resets: hides Phase 2, shows Phase 1, clears error

**Results** — same Extracted Data + Raw JSON tabs as today. No History tab.

---

### Advanced Crawl page (`ui_advanced_crawl.py`)

Identical layout to the current `ui.py` crawl form. Changes only:

1. History tab removed from results area
2. `run_crawl()`, `_build_request()`, `_validate_url()`, `_sample_tags()` imported from `ui_shared.py` instead of defined inline

No behaviour changes. Users familiar with the current UI see the same page.

---

### Storage page (`ui_storage.py`)

**Panel 1 — Bucket stats** (loads on page visit via `demo.load()`)

Three stat chips rendered as `gr.HTML`:
- Total files
- Total size (human-readable: KB/MB/GB)
- Last crawl timestamp

"Refresh" button re-fetches `GET /storage` and updates the chips.

503 (storage not configured) shows a warning banner instead of stats.

**Panel 2 — Object list**

`gr.Dataframe` columns: `job_id`, `size`, `last_modified`.

Below the dataframe, two action inputs:
- `gr.Textbox` "Job ID" (paste from table) + `gr.Radio` format (json/jsonl) + "Download" button → calls `download_from_storage()`
- `gr.Textbox` "Job ID to delete" + "Delete" button → triggers confirmation

Delete confirmation: `gr.Group` (styled as a modal-like warning box) shown inline when Delete is clicked, containing the message "Delete crawl-{job_id}.json? This cannot be undone." with Cancel and Confirm buttons. Confirm sends `DELETE /storage/{job_id}`. On success: refreshes the object list. On 404: shows inline error.

**Panel 3 — DuckDB query**

Promoted from the old History tab:
- Seed URL, goal, date from, date to, limit inputs
- "Search" button → calls `query_history()`
- Results `gr.Dataframe`: `job_id`, `seed_url`, `goal`, `generated_at`, `total_pages`
- "Download" button below results: takes selected `job_id` from a `gr.Textbox` (user pastes from table) + format radio → downloads from `/storage/{job_id}`

---

## Data Flow

```
Quick Crawl:
  user types prompt
    → POST /parse → parsed fields dict
    → user edits fields
    → POST /crawl (full field set, no prompt field)
    → poll GET /crawl/{id}
    → GET /crawl/{id}/result

Advanced Crawl:
  user fills form
    → POST /crawl (full field set)
    → poll GET /crawl/{id}
    → GET /crawl/{id}/result

Storage:
  page load → GET /storage → stats + object list
  query     → POST /query  → CrawlSummary list
  download  → GET /storage/{job_id}
  delete    → DELETE /storage/{job_id} → refresh GET /storage
```

---

## Shared helpers (`ui_shared.py`)

Functions moved from `ui.py`:

```python
def _validate_url(seed_url: str | None) -> str
def _build_request(...) -> dict
async def run_crawl(...) -> AsyncIterator[tuple]
def _sample_tags(samples, target) -> None
```

Both crawl pages import from `ui_shared`. Neither imports from the other.

---

## What Is Not Changed

- `ui_results.py` — result table rendering, unchanged
- `client.py` functions: `start_crawl`, `poll_until_done`, `download_result`, `query_history`, `download_from_storage` — unchanged
- All CSS variables and the result split-view layout — moved to `ui_styles.py`, unchanged
- Engine modules other than `storage.py` and `service.py`

---

## Explicitly Out of Scope

- Aggregate analytics or diff between stored runs
- Per-depth CSS selector configuration
- Authentication or access control on the UI
