# Extracted Data UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a searchable, sortable extracted-data table with a selected-record detail panel while preserving the existing raw JSON preview and downloads.

**Architecture:** Keep crawl execution and output serialization unchanged. Add a focused `src/ui_results.py` presentation module that converts page payloads into dynamic table rows and safe detail HTML, then wire those outputs into Gradio tabs and state in `src/ui.py`. Use Gradio 6.0.1's native dataframe search, browser-side sorting, and `SelectData.row_value` selection event.

**Tech Stack:** Python 3.11, Gradio 6.0.1, Pydantic, pytest, Ruff, uv.

---

### Task 1: Result Presentation Model

**Files:**
- Create: `src/ui_results.py`
- Modify: `tests/test_ui.py`

- [ ] **Step 1: Write failing tests for extracted and all-page views**

Add fixtures containing successful extraction, extraction failure, and crawl failure records.
Assert that extracted mode includes only successful extracted records, all-pages mode includes
every page, dynamic columns are the union of extracted keys, and title-like fields are ordered
first.

```python
def test_build_result_table_filters_pages_and_unions_dynamic_columns():
    payload = {"pages": [_extracted_page(), _extraction_failure(), _crawl_failure()]}

    extracted = build_result_table(payload, mode="Extracted")
    all_pages = build_result_table(payload, mode="All pages")

    assert extracted.headers[:3] == ["#", "Status", "article_title"]
    assert {"author", "stock_tickers"} <= set(extracted.headers)
    assert len(extracted.rows) == 1
    assert len(all_pages.rows) == 3
```

- [ ] **Step 2: Run tests and verify RED**

```bash
uv run pytest tests/test_ui.py -q
```

Expected: collection fails because `src.ui_results` does not exist.

- [ ] **Step 3: Implement the result table model**

Create immutable presentation records:

```python
@dataclass(frozen=True)
class ResultTable:
    headers: list[str]
    rows: list[list[str | int]]
    records: list[dict]
    empty_message: str
```

Implement:

```python
def build_result_table(
    payload: dict,
    mode: str = "Extracted",
    *,
    extraction_requested: bool = True,
) -> ResultTable
```

Use stable one-based record identifiers in the `#` column. Derive status from page success,
`metadata.extracted`, and `metadata.extraction_error`. Use an em dash for missing fields.

- [ ] **Step 4: Run tests and verify GREEN**

```bash
uv run pytest tests/test_ui.py -q
```

Expected: the new table-model tests pass.

### Task 2: Complex Values and Detail Panel

**Files:**
- Modify: `src/ui_results.py`
- Modify: `tests/test_ui.py`

- [ ] **Step 1: Write failing formatting and selection tests**

Cover scalar, list, and object table formatting; complete values in detail HTML; escaped
untrusted text; source URL; extraction errors; and selection using the stable record number
from `gr.SelectData.row_value`.

```python
def test_format_table_value_compacts_complex_values():
    assert format_table_value(["ACB", "SHB"]) == "ACB, SHB"
    assert format_table_value({"shares": "102 million", "value": "10 trillion"}) == (
        "shares: 102 million; value: 10 trillion"
    )


def test_select_result_detail_uses_stable_record_number_after_sorting():
    event = SimpleNamespace(row_value=[3, "Crawl failed"])
    detail = select_result_detail(records, event)
    assert "https://example.com/failed" in detail
```

- [ ] **Step 2: Run tests and verify RED**

```bash
uv run pytest tests/test_ui.py -q
```

Expected: tests fail because formatting and detail helpers are missing.

- [ ] **Step 3: Implement safe formatting and details**

Implement:

```python
def format_table_value(value: object, max_chars: int = 120) -> str
def render_result_detail(record: dict | None, empty_message: str = "") -> str
def select_result_detail(records: list[dict], event: gr.SelectData) -> str
```

Escape all extracted text with `html.escape`. Render scalar arrays as chips, objects as
key-value rows, long text with wrapping, source URL as a safe external link, and explicit
status text. Never include article markdown.

- [ ] **Step 4: Run tests and verify GREEN**

```bash
uv run pytest tests/test_ui.py -q
```

Expected: formatting and detail tests pass.

### Task 3: Gradio Result Tabs and Events

**Files:**
- Modify: `src/ui.py`
- Modify: `tests/test_ui.py`

- [ ] **Step 1: Write failing crawl-output tests**

Update the `run_crawl()` tests to expect table data, detail HTML, result records, unchanged raw
payload, and download path. Add a component-configuration test asserting native search,
read-only interaction, row selection wiring, and extracted/all-page mode controls.

```python
status, table, detail, records, payload, download = await run_crawl(...)

assert table.headers[:2] == ["#", "Status"]
assert records[0]["source_url"] == "https://cafef.vn"
assert payload["pages"][0]["title"] == "CafeF"
```

- [ ] **Step 2: Run tests and verify RED**

```bash
uv run pytest tests/test_ui.py -q
```

Expected: tuple-shape and component tests fail against the JSON-only interface.

- [ ] **Step 3: Wire the approved result layout**

Change `run_crawl()` to return:

```python
tuple[str, gr.Dataframe, str, list[dict], dict, str]
```

Add:

- `gr.State` for result records, complete payload, and whether extraction was requested
- `gr.Tabs` containing `Extracted Data` and `Raw JSON`
- `gr.Radio(["Extracted", "All pages"])` above the table
- `gr.Dataframe` with `show_search="search"`, built-in sorting, `max_chars=120`,
  `interactive=False`, `show_row_numbers=False`, and horizontal scrolling
- A right-side `gr.HTML` detail panel
- A mode-change handler that rebuilds rows and selects the first visible record
- A dataframe `select` handler that uses `SelectData.row_value[0]`

Preserve `write_results()` input and the raw payload returned to `gr.JSON`.

- [ ] **Step 4: Run UI tests and verify GREEN**

```bash
uv run pytest tests/test_ui.py -q
```

Expected: all UI tests pass.

### Task 4: Visual Styling and Empty States

**Files:**
- Modify: `src/ui.py`
- Modify: `tests/test_ui.py`

- [ ] **Step 1: Write failing empty-state tests**

Verify no extraction prompt directs users to Raw JSON, all-failed extraction exposes failed
pages in All pages, and mode changes with no matching rows produce a clear empty detail.

- [ ] **Step 2: Run tests and verify RED**

```bash
uv run pytest tests/test_ui.py -q
```

Expected: empty-state assertions fail.

- [ ] **Step 3: Add scoped result-view CSS**

Style only result-area classes: result header, compact page-mode toggle, selected-row
affordance, detail fields/chips/status, responsive stacking below 850 px, and horizontal table
scrolling. Keep the existing input panels and sample tags unchanged.

- [ ] **Step 4: Run tests and verify GREEN**

```bash
uv run pytest tests/test_ui.py -q
```

Expected: all empty-state and UI tests pass.

### Task 5: Verification

**Files:**
- Verify: `src/ui.py`
- Verify: `src/ui_results.py`
- Verify: `tests/test_ui.py`

- [ ] **Step 1: Format and lint**

```bash
uv run ruff format src/ui.py src/ui_results.py tests/test_ui.py
uv run ruff check .
```

Expected: no formatting or lint errors.

- [ ] **Step 2: Run the non-network suite**

```bash
uv run pytest -m "not integration" -q
```

Expected: all unit tests pass.

- [ ] **Step 3: Launch and inspect the interface**

```bash
uv run python app.py
```

Verify the result tabs, dynamic columns, native search and sorting, extracted/all-page mode,
selection detail, raw JSON, responsive stacking, and download control in the browser.

- [ ] **Step 4: Inspect repository changes**

```bash
git diff --check
git status --short
```

Expected: only task-related files plus pre-existing user changes are modified.
