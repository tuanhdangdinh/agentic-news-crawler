# Financial Figures Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render `key_financial_figures` as an accessible compact ledger with expandable context while preserving generic structured-field rendering and crawl output.

**Architecture:** Add a dedicated financial-figure HTML renderer in `src/ui_results.py` and call it only for the `key_financial_figures` detail field. Extend the existing result-view JavaScript and scoped CSS in `src/ui.py` for per-row context disclosure and a `Show N more` control; keep all interaction browser-local and leave Gradio state, extraction, and serialization unchanged.

**Tech Stack:** Python 3.11, HTML, CSS, browser JavaScript, Gradio 6.0.1, pytest, Ruff, uv.

---

### Task 1: Financial Figure Ledger Renderer

**Files:**
- Modify: `src/ui_results.py:52-164`
- Modify: `tests/test_ui_results.py`

- [ ] **Step 1: Add failing tests for both observed schemas**

Import `render_financial_figures` and `render_result_detail`, then add:

```python
from src.ui_results import (
    build_result_table,
    render_financial_figures,
    render_result_detail,
    render_result_table_html,
)


def test_render_financial_figures_maps_metric_schema():
    output = render_financial_figures(
        [
            {
                "metric": "Price increase",
                "value": "17%",
                "entity": "ACB",
                "period": "14 trading sessions",
                "context": "ACB stock price increased nearly 17%.",
            }
        ],
        element_prefix="record-1",
    )

    assert "financial-ledger" in output
    assert "Price increase" in output
    assert "17%" in output
    assert "ACB · 14 trading sessions" in output
    assert 'aria-expanded="false"' in output
    assert 'aria-controls="record-1-figure-context-0"' in output
    assert 'id="record-1-figure-context-0"' in output
    assert "ACB stock price increased nearly 17%." in output
    assert "hidden" in output


def test_render_financial_figures_maps_figure_value_schema():
    output = render_financial_figures(
        [{"figure": "Cash equivalents", "value": 6758}],
        element_prefix="record-1",
    )

    assert "Cash equivalents" in output
    assert ">6758<" in output
    assert "financial-figure-meta" not in output
    assert "financial-figure-toggle" not in output
```

- [ ] **Step 2: Run the schema tests and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/crawl-tool-c1-homebrew-venv \
  uv run pytest \
  tests/test_ui_results.py::test_render_financial_figures_maps_metric_schema \
  tests/test_ui_results.py::test_render_financial_figures_maps_figure_value_schema -q
```

Expected: collection fails because `render_financial_figures` does not exist.

- [ ] **Step 3: Implement the minimal ledger renderer**

Add a public renderer with a Google-style docstring and private mapping helpers:

```python
_FINANCIAL_LABEL_KEYS = ("metric", "figure")
_FINANCIAL_RESERVED_KEYS = {"value", "entity", "period", "context"}


def _financial_label(item: dict) -> str:
    for key in _FINANCIAL_LABEL_KEYS:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    for key, value in item.items():
        if key not in _FINANCIAL_RESERVED_KEYS and not isinstance(value, (dict, list)):
            if value not in (None, ""):
                return str(value)
    return "Financial figure"


def render_financial_figures(
    items: list[dict],
    *,
    element_prefix: str,
    max_rows: int = 12,
) -> str:
    """Render financial figures as a compact disclosure ledger.

    Args:
        items: Extracted financial figure dictionaries.
        element_prefix: DOM-safe prefix that keeps disclosure identifiers unique.
        max_rows: Number of figures visible before the reveal control.

    Returns:
        Escaped HTML for the financial figure ledger.
    """
```

Build each row from:

- `_financial_label(item)` for the primary label
- `item.get("value")`, using `_EM_DASH` when missing
- non-empty `entity` and `period` joined with ` · `
- a `<button type="button">` only when `context` is non-empty
- a context `<div hidden>` whose ID is
  `f"{element_prefix}-figure-context-{index}"`

Escape label, value, metadata, context, and identifiers with `html.escape(..., quote=True)`.
Use `onclick="rtToggleFigure(this)"`, `aria-expanded="false"`, and `aria-controls` on each
context button.

- [ ] **Step 4: Run the schema tests and verify GREEN**

Run the command from Step 2.

Expected: both tests pass.

- [ ] **Step 5: Add failing integration and edge-state tests**

Add:

```python
def test_render_result_detail_specializes_only_key_financial_figures():
    record = {
        "status": "Extracted",
        "extracted": {
            "key_financial_figures": [{"metric": "Revenue", "value": "10 trillion VND"}],
            "directors": [{"name": "Nguyen Van A", "role": "CEO"}],
        },
    }

    output = render_result_detail(record, element_prefix="record-1")

    assert output.count("financial-ledger") == 1
    assert "10 trillion VND" in output
    assert "figures-table" in output
    assert "<th>name</th>" in output


def test_render_financial_figures_escapes_values_and_uses_fallbacks():
    output = render_financial_figures(
        [
            {
                "label_text": "<script>alert(1)</script>",
                "value": None,
                "entity": "",
                "period": None,
                "context": "<b>unsafe</b>",
            }
        ],
        element_prefix="record-1",
    )

    assert "<script>" not in output
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in output
    assert "&lt;b&gt;unsafe&lt;/b&gt;" in output
    assert ">—<" in output
    assert "financial-figure-meta" not in output
```

Use the literal em dash in the assertion rather than importing the private constant.

- [ ] **Step 6: Run the new tests and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/crawl-tool-c1-homebrew-venv \
  uv run pytest \
  tests/test_ui_results.py::test_render_result_detail_specializes_only_key_financial_figures \
  tests/test_ui_results.py::test_render_financial_figures_escapes_values_and_uses_fallbacks -q
```

Expected: the detail renderer still sends both fields through `render_list_of_objects()`, or
the new `element_prefix` argument is not accepted.

- [ ] **Step 7: Route only the financial field to the ledger**

Change the public signature to:

```python
def render_result_detail(
    record: dict | None,
    empty_message: str = "",
    *,
    element_prefix: str = "result-detail",
) -> str:
```

In the extracted-field loop, place this branch before the generic list-of-dictionaries branch:

```python
elif (
    k == "key_financial_figures"
    and isinstance(v, list)
    and v
    and all(isinstance(item, dict) for item in v)
):
    parts.append(
        f"<dd>{render_financial_figures(v, element_prefix=element_prefix)}</dd>"
    )
```

Keep every other branch unchanged. In `render_result_table_html()`, make each detail record's
IDs unique:

```python
detail_html = render_result_detail(record, element_prefix=det_id)
```

- [ ] **Step 8: Run all renderer tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/crawl-tool-c1-homebrew-venv \
  uv run pytest tests/test_ui_results.py -q
```

Expected: all tests in `tests/test_ui_results.py` pass.

- [ ] **Step 9: Format, lint, and commit the renderer**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/crawl-tool-c1-homebrew-venv \
  uv run ruff format src/ui_results.py tests/test_ui_results.py
UV_PROJECT_ENVIRONMENT=/private/tmp/crawl-tool-c1-homebrew-venv \
  uv run ruff check src/ui_results.py tests/test_ui_results.py
git add src/ui_results.py tests/test_ui_results.py
git commit -m "feat: render financial figures as ledger"
```

Expected: Ruff reports no errors and the commit includes only the renderer and its tests.

---

### Task 2: Context Disclosure and Row Reveal

**Files:**
- Modify: `src/ui_results.py:80-180`
- Modify: `src/ui.py:24-73`
- Modify: `src/ui.py:315-356`
- Modify: `tests/test_ui_results.py`
- Modify: `tests/test_dev_ui.py`

- [ ] **Step 1: Add a failing overflow-markup test**

Add:

```python
def test_render_financial_figures_hides_rows_after_limit():
    figures = [{"metric": f"Metric {index}", "value": index} for index in range(14)]

    output = render_financial_figures(
        figures,
        element_prefix="record-1",
        max_rows=12,
    )

    assert output.count('class="financial-figure"') == 14
    assert 'id="record-1-figure-extra"' in output
    assert 'class="financial-figure-extra" hidden' in output
    assert 'aria-controls="record-1-figure-extra"' in output
    assert 'aria-expanded="false"' in output
    assert "Show 2 more" in output
    assert 'onclick="rtShowFigures(this)"' in output
```

- [ ] **Step 2: Run the overflow test and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/crawl-tool-c1-homebrew-venv \
  uv run pytest \
  tests/test_ui_results.py::test_render_financial_figures_hides_rows_after_limit -q
```

Expected: the renderer does not yet emit the extra-row container or reveal button.

- [ ] **Step 3: Implement the 12-row reveal boundary**

Render `items[:max_rows]` in the main ledger body. When `len(items) > max_rows`, render the
remaining rows in:

```html
<div class="financial-figure-extra" id="{prefix}-figure-extra" hidden>
  ...remaining financial-figure rows...
</div>
<button
  type="button"
  class="financial-figure-more"
  aria-expanded="false"
  aria-controls="{prefix}-figure-extra"
  onclick="rtShowFigures(this)"
>
  Show {extra_count} more
</button>
```

Store the expanded label in `data-expanded-label="Show fewer"` so the browser helper can
toggle text without reconstructing it.

- [ ] **Step 4: Run the overflow test and verify GREEN**

Run the command from Step 2.

Expected: the test passes.

- [ ] **Step 5: Add failing JavaScript installation tests**

Extend `test_dev_ui_head_installs_result_handlers_in_page_scope()`:

```python
assert "window.rtToggleFigure" in DEV_UI_HEAD
assert "window.rtShowFigures" in DEV_UI_HEAD
assert "aria-expanded" in DEV_UI_HEAD
```

- [ ] **Step 6: Run the JavaScript installation test and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/crawl-tool-c1-homebrew-venv \
  uv run pytest tests/test_dev_ui.py::test_dev_ui_head_installs_result_handlers_in_page_scope -q
```

Expected: `DEV_UI_HEAD` does not contain the two new window functions.

- [ ] **Step 7: Add browser-local disclosure helpers**

Inside `_RESULT_JS`, before the closing `if` block, add:

```javascript
  window.rtToggleFigure = function(button) {
    const target = document.getElementById(button.getAttribute('aria-controls'));
    if (!target) return;
    const expanded = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', String(!expanded));
    target.hidden = expanded;
  };

  window.rtShowFigures = function(button) {
    const target = document.getElementById(button.getAttribute('aria-controls'));
    if (!target) return;
    const expanded = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', String(!expanded));
    target.hidden = expanded;
    const collapsedLabel = button.dataset.collapsedLabel;
    const expandedLabel = button.dataset.expandedLabel;
    button.textContent = expanded ? collapsedLabel : expandedLabel;
  };
```

Set both `data-collapsed-label` and `data-expanded-label` in renderer output. Native buttons
provide Enter and Space activation without custom key handlers.

- [ ] **Step 8: Run the JavaScript installation test and verify GREEN**

Run the command from Step 6.

Expected: the test passes.

- [ ] **Step 9: Add scoped compact-ledger CSS**

Append styles near `.figures-table` in `CUSTOM_CSS`:

```css
.financial-ledger {
  border: 1px solid var(--crawler-border);
  border-radius: 10px;
  overflow: hidden;
}
.financial-figure {
  border-bottom: 1px solid var(--crawler-border);
}
.financial-figure:last-child {
  border-bottom: 0;
}
.financial-figure-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 0.75rem;
  align-items: center;
  padding: 0.75rem 0.85rem;
}
.financial-figure-label {
  color: var(--crawler-ink);
  font-size: 0.82rem;
  font-weight: 700;
  line-height: 1.35;
}
.financial-figure-meta {
  color: var(--crawler-muted);
  font-size: 0.7rem;
  margin-top: 0.2rem;
}
.financial-figure-value {
  color: var(--crawler-accent);
  font-size: 0.82rem;
  font-weight: 800;
  text-align: right;
}
.financial-figure-toggle,
.financial-figure-more {
  border: 1px solid var(--crawler-border);
  background: var(--crawler-bg-soft);
  color: var(--crawler-muted);
  cursor: pointer;
}
.financial-figure-toggle {
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 6px;
}
.financial-figure-toggle:focus-visible,
.financial-figure-more:focus-visible {
  outline: 2px solid var(--crawler-accent);
  outline-offset: 2px;
}
.financial-figure-context {
  padding: 0.65rem 0.85rem;
  border-left: 2px solid var(--crawler-accent);
  background: rgba(201, 79, 45, 0.06);
  color: var(--crawler-muted);
  font-size: 0.75rem;
  line-height: 1.5;
}
.financial-figure-more {
  width: 100%;
  padding: 0.6rem;
  border-width: 1px 0 0;
  font-size: 0.75rem;
  font-weight: 700;
}
@media (max-width: 640px) {
  .financial-figure-main {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .financial-figure-toggle {
    grid-column: 2;
  }
}
```

Use a text glyph such as `⌄` in the button and rotate it under
`.financial-figure-toggle[aria-expanded="true"]`; keep the visible label in `aria-label`.

- [ ] **Step 10: Run scoped tests, format, lint, and commit**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/crawl-tool-c1-homebrew-venv \
  uv run pytest tests/test_ui_results.py tests/test_dev_ui.py -q
UV_PROJECT_ENVIRONMENT=/private/tmp/crawl-tool-c1-homebrew-venv \
  uv run ruff format src/ui.py src/ui_results.py tests/test_ui_results.py tests/test_dev_ui.py
UV_PROJECT_ENVIRONMENT=/private/tmp/crawl-tool-c1-homebrew-venv \
  uv run ruff check src/ui.py src/ui_results.py tests/test_ui_results.py tests/test_dev_ui.py
git add src/ui.py src/ui_results.py tests/test_ui_results.py tests/test_dev_ui.py
git commit -m "feat: add financial figure disclosures"
```

Expected: scoped tests pass, Ruff reports no errors, and the commit includes only interaction,
styling, and related tests.

---

### Task 3: Real-Payload Verification

**Files:**
- Verify: `dev_ui.py`
- Verify: `src/ui.py`
- Verify: `src/ui_results.py`
- Verify: `tests/test_dev_ui.py`
- Verify: `tests/test_ui_results.py`

- [ ] **Step 1: Run the complete automated suite**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/crawl-tool-c1-homebrew-venv \
  uv run pytest -q
```

Expected: all tests pass; environment-dependent tests may remain skipped.

- [ ] **Step 2: Run repository lint checks**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/crawl-tool-c1-homebrew-venv \
  uv run ruff check .
git diff --check
```

Expected: Ruff reports no errors in changed files. If `git diff --check` reports pre-existing
whitespace in unrelated dirty files, record it without modifying those files.

- [ ] **Step 3: Launch the development UI with a financial fixture**

Run:

```bash
GRADIO_ANALYTICS_ENABLED=False HF_HUB_DISABLE_TELEMETRY=1 \
UV_PROJECT_ENVIRONMENT=/private/tmp/crawl-tool-c1-homebrew-venv \
  uv run python dev_ui.py out_tuoitre.json
```

Expected: Gradio starts on a local URL and preloads an article containing
`key_financial_figures`.

- [ ] **Step 4: Verify behavior in the in-app browser**

Open the reported local URL with the Browser plugin and verify:

- One article remains one master-table row.
- The selected record shows compact financial ledger rows.
- Metric and value are visually dominant.
- Entity and period appear only when present.
- Context is hidden initially.
- Clicking and keyboard-activating a disclosure changes `aria-expanded` and reveals context.
- `Show N more` appears for more than 12 figures and reveals the remainder.
- Long labels and values wrap without horizontal overflow.
- Selecting another article still updates the detail panel.

- [ ] **Step 5: Stop the development server**

Send `Ctrl-C` to the active development UI process and confirm the server exits.

- [ ] **Step 6: Record final status**

Run:

```bash
git status --short
git log -3 --oneline
```

Expected: the ledger changes are committed, while unrelated pre-existing workspace changes
remain untouched.
