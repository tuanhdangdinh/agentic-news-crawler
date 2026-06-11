"""Presentation helpers for the crawl result area."""

from __future__ import annotations

import html
from dataclasses import dataclass

_EM_DASH = "—"
_TITLE_KEY_FRAGMENTS = {"title", "headline", "name", "subject"}
_LABEL_KEY_FRAGMENTS = {"metric", "name", "label", "title", "indicator", "field", "item"}
_VALUE_KEY_FRAGMENTS = {"value", "amount", "figure", "price", "rate", "change", "level", "score"}
_VERBOSE_KEY_FRAGMENTS = {"context", "description", "summary", "detail", "text", "body", "note"}

_STATUS_BADGE = {
    "Extracted": "status-ok",
    "Crawl failed": "status-err",
    "Extract failed": "status-err",
}


# ── Value formatters ─────────────────────────────────────────────────────────


def format_table_value(value: object, max_chars: int = 120) -> str:
    if value is None:
        return _EM_DASH
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            # Find a label key to name the items by
            label_key = next(
                (k for k in value[0] if any(f in k.lower() for f in _LABEL_KEY_FRAGMENTS)),
                None,
            )
            if label_key:
                labels = [str(item.get(label_key, "")) for item in value[:3] if item.get(label_key)]
                text = ", ".join(labels)
                extra = len(value) - len(labels)
                if extra > 0:
                    text += f" +{extra} more"
            else:
                n = len(value)
                text = f"{n} item{'s' if n != 1 else ''}"
        else:
            text = ", ".join(str(item) for item in value)
    elif isinstance(value, dict):
        pairs = list(value.items())[:4]
        text = "; ".join(f"{k}: {v}" for k, v in pairs)
        if len(value) > 4:
            text += f"; +{len(value) - 4} more"
    else:
        text = str(value)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    return text or _EM_DASH


# ── Financial figures ledger ──────────────────────────────────────────────────

_FINANCIAL_LABEL_KEYS = ("metric", "figure")
_FINANCIAL_RESERVED_KEYS = {"value", "entity", "period", "context"}


def _financial_label(item: dict) -> str:
    for key in _FINANCIAL_LABEL_KEYS:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    for key, value in item.items():
        if (
            key not in _FINANCIAL_RESERVED_KEYS
            and not isinstance(value, (dict, list))
            and value not in (None, "")
        ):
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
    if not items:
        return f'<span class="missing">{_EM_DASH}</span>'

    def render_row(item: dict, index: int) -> str:
        label = _financial_label(item)
        val = item.get("value")
        val_str = str(val) if val is not None and val != "" else _EM_DASH

        meta_parts = []
        for key in ("entity", "period"):
            m_val = item.get(key)
            if m_val not in (None, ""):
                meta_parts.append(str(m_val))
        meta_text = " · ".join(meta_parts)

        context = item.get("context")
        has_context = context not in (None, "")

        row_id_escaped = html.escape(f"{element_prefix}-figure-context-{index}", quote=True)

        btn_html = ""
        context_html = ""
        if has_context:
            btn_html = (
                f'<button type="button" class="financial-figure-toggle" '
                f'aria-expanded="false" aria-controls="{row_id_escaped}" '
                f'aria-label="Toggle context" onclick="rtToggleFigure(this)">⌄</button>'
            )
            context_html = (
                f'<div class="financial-figure-context" id="{row_id_escaped}" hidden>'
                f"{html.escape(str(context))}"
                f"</div>"
            )

        meta_html = ""
        if meta_text:
            meta_html = f'<div class="financial-figure-meta">{html.escape(meta_text)}</div>'

        return (
            f'<div class="financial-figure">'
            f'<div class="financial-figure-main">'
            f"<div>"
            f'<div class="financial-figure-label">{html.escape(label)}</div>'
            f"{meta_html}"
            f"</div>"
            f'<div class="financial-figure-value">{html.escape(val_str)}</div>'
            f"{btn_html}"
            f"</div>"
            f"{context_html}"
            f"</div>"
        )

    visible_items = items[:max_rows]
    extra_items = items[max_rows:]

    parts = []
    parts.append('<div class="financial-ledger">')

    for idx, item in enumerate(visible_items):
        parts.append(render_row(item, idx))

    if extra_items:
        extra_prefix_escaped = html.escape(f"{element_prefix}-figure-extra", quote=True)
        parts.append(f'<div class="financial-figure-extra" id="{extra_prefix_escaped}" hidden>')
        for idx, item in enumerate(extra_items, start=max_rows):
            parts.append(render_row(item, idx))
        parts.append("</div>")

        extra_count = len(extra_items)
        collapsed_label = f"Show {extra_count} more"
        expanded_label = "Show fewer"
        parts.append(
            f'<button type="button" class="financial-figure-more" '
            f'aria-expanded="false" aria-controls="{extra_prefix_escaped}" '
            f'data-collapsed-label="{html.escape(collapsed_label, quote=True)}" '
            f'data-expanded-label="{html.escape(expanded_label, quote=True)}" '
            f'onclick="rtShowFigures(this)">'
            f"{html.escape(collapsed_label)}"
            f"</button>"
        )

    parts.append("</div>")
    return "\n".join(parts)


# ── List-of-objects mini-table ────────────────────────────────────────────────


def _obj_list_columns(items: list[dict]) -> list[str]:
    """Return ordered, deduplicated column keys, verbose keys excluded."""
    seen: dict[str, None] = {}
    for item in items:
        for k in item:
            seen[k] = None

    def _priority(k: str) -> int:
        lower = k.lower()
        if any(f in lower for f in _LABEL_KEY_FRAGMENTS):
            return 0
        if any(f in lower for f in _VALUE_KEY_FRAGMENTS):
            return 1
        if any(f in lower for f in _VERBOSE_KEY_FRAGMENTS):
            return 99
        return 2

    return [k for k in sorted(seen, key=_priority) if _priority(k) < 99]


def render_list_of_objects(items: list[dict], max_rows: int = 12) -> str:
    if not items:
        return f'<span class="missing">{_EM_DASH}</span>'
    columns = _obj_list_columns(items)
    if not columns:
        return f'<span class="missing">{_EM_DASH}</span>'

    head_cells = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    body_parts: list[str] = []
    for item in items[:max_rows]:
        cells = []
        for c in columns:
            v = item.get(c)
            if v is None:
                cells.append(f'<td class="missing">{_EM_DASH}</td>')
            else:
                text = str(v)
                if len(text) > 80:
                    text = text[:80].rstrip() + "…"
                cells.append(f"<td>{html.escape(text)}</td>")
        body_parts.append(f"<tr>{''.join(cells)}</tr>")

    extra = len(items) - max_rows
    if extra > 0:
        body_parts.append(
            f'<tr><td colspan="{len(columns)}" class="figures-more">… {extra} more</td></tr>'
        )

    return (
        f'<table class="figures-table">'
        f"<thead><tr>{head_cells}</tr></thead>"
        f"<tbody>{''.join(body_parts)}</tbody>"
        f"</table>"
    )


# ── Detail panel ─────────────────────────────────────────────────────────────


def render_result_detail(
    record: dict | None,
    empty_message: str = "",
    *,
    element_prefix: str = "result-detail",
) -> str:
    if record is None:
        msg = html.escape(empty_message) if empty_message else "Select a row to see details."
        return f'<div class="result-detail result-detail-empty"><p>{msg}</p></div>'

    status = record.get("status", "")
    source_url = record.get("source_url", "")
    extracted = record.get("extracted") or {}
    error = record.get("error")
    extraction_error = record.get("extraction_error")

    badge_cls = _STATUS_BADGE.get(status, "status-warn")
    parts: list[str] = [
        '<div class="result-detail">',
        '<div class="result-detail-header">',
        f'<span class="status-badge {badge_cls}">{html.escape(status)}</span>',
        "</div>",
        '<dl class="result-detail-fields">',
    ]

    for k, v in extracted.items():
        parts.append(f"<dt>{html.escape(str(k))}</dt>")
        if v is None:
            parts.append(f'<dd class="missing">{_EM_DASH}</dd>')
        elif (
            k == "key_financial_figures"
            and isinstance(v, list)
            and v
            and all(isinstance(item, dict) for item in v)
        ):
            parts.append(f"<dd>{render_financial_figures(v, element_prefix=element_prefix)}</dd>")
        elif isinstance(v, list) and v and all(isinstance(item, dict) for item in v):
            parts.append(f"<dd>{render_list_of_objects(v)}</dd>")
        elif isinstance(v, list) and all(not isinstance(item, (dict, list)) for item in v):
            chips = "".join(f'<span class="chip">{html.escape(str(item))}</span>' for item in v)
            parts.append(f'<dd class="chip-list">{chips}</dd>')
        elif isinstance(v, dict):
            rows_html = "".join(
                f'<span class="kv-row">'
                f'<span class="kv-key">{html.escape(str(dk))}</span> '
                f"{html.escape(str(dv))}"
                f"</span>"
                for dk, dv in v.items()
            )
            parts.append(f'<dd class="kv-block">{rows_html}</dd>')
        else:
            parts.append(f"<dd>{html.escape(str(v))}</dd>")

    if source_url:
        safe_url = html.escape(source_url)
        parts.append("<dt>source_url</dt>")
        parts.append(
            f'<dd><a href="{safe_url}" target="_blank" rel="noopener noreferrer">'
            f"{safe_url}</a></dd>"
        )

    if error:
        parts.append(f'<dt>crawl_error</dt><dd class="error-text">{html.escape(str(error))}</dd>')
    if extraction_error:
        parts.append(
            f"<dt>extraction_error</dt>"
            f'<dd class="error-text">{html.escape(str(extraction_error))}</dd>'
        )

    parts += ["</dl>", "</div>"]
    return "\n".join(parts)


# ── Accordion table ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResultTable:
    headers: list[str]
    rows: list[list[str | int]]
    records: list[dict]
    empty_message: str


def _extracted(page: dict) -> dict | None:
    return page.get("metadata", {}).get("extracted") or None


def _extraction_error(page: dict) -> str | None:
    return page.get("metadata", {}).get("extraction_error") or None


def _page_status(page: dict) -> str:
    if not page.get("success", True):
        return "Crawl failed"
    if _extraction_error(page):
        return "Extract failed"
    if _extracted(page):
        return "Extracted"
    return "No data"


def _is_title_key(key: str) -> bool:
    lower = key.lower()
    return any(frag in lower for frag in _TITLE_KEY_FRAGMENTS)


def _union_extracted_keys(pages: list[dict]) -> list[str]:
    seen: dict[str, None] = {}
    title_keys: list[str] = []
    other_keys: list[str] = []
    for page in pages:
        ex = _extracted(page)
        if not ex:
            continue
        for k in ex:
            if k in seen:
                continue
            seen[k] = None
            if _is_title_key(k):
                title_keys.append(k)
            else:
                other_keys.append(k)
    return title_keys + other_keys


def build_result_table(
    payload: dict,
    mode: str = "Extracted",
    *,
    extraction_requested: bool = True,
) -> ResultTable:
    all_pages = payload.get("pages", [])

    if not extraction_requested:
        return ResultTable(
            headers=["#", "URL", "Title"],
            rows=[
                [i + 1, p.get("url", ""), p.get("title") or _EM_DASH]
                for i, p in enumerate(all_pages)
            ],
            records=[
                {
                    "row_number": i + 1,
                    "status": _page_status(p),
                    "source_url": p.get("url", ""),
                    "extracted": {},
                    "error": p.get("error"),
                    "extraction_error": None,
                }
                for i, p in enumerate(all_pages)
            ],
            empty_message=(
                "Structured extraction was not requested. See Raw JSON for complete page content."
            ),
        )

    pages = [p for p in all_pages if _extracted(p)] if mode == "Extracted" else list(all_pages)
    extracted_keys = _union_extracted_keys(all_pages)
    headers = ["#", "Status"] + extracted_keys

    rows: list[list[str | int]] = []
    records: list[dict] = []

    for idx, page in enumerate(pages, start=1):
        ex = _extracted(page) or {}
        status = _page_status(page)
        row: list[str | int] = [idx, status]
        for key in extracted_keys:
            row.append(format_table_value(ex.get(key)))
        rows.append(row)
        records.append(
            {
                "row_number": idx,
                "status": status,
                "source_url": page.get("url", ""),
                "extracted": ex,
                "error": page.get("error"),
                "extraction_error": _extraction_error(page),
            }
        )

    if not pages and mode == "Extracted":
        empty_message = (
            "No pages with successful extraction. Switch to “All pages” to inspect crawl results."
        )
    elif not pages:
        empty_message = "No pages collected."
    else:
        empty_message = ""

    return ResultTable(
        headers=headers,
        rows=rows,
        records=records,
        empty_message=empty_message,
    )


def render_result_table_html(result_table: ResultTable) -> str:
    """Render a Master-Detail split layout as an HTML string."""
    if not result_table.rows:
        msg = html.escape(result_table.empty_message or "No results.")
        return f'<div class="rt-empty"><p>{msg}</p></div>'

    headers = result_table.headers
    head_cells = "".join(f'<th class="rt-th">{html.escape(str(h))}</th>' for h in headers)

    body_parts: list[str] = []
    detail_parts: list[str] = []

    for i, (row, record) in enumerate(zip(result_table.rows, result_table.records, strict=True)):
        det_id = f"rt-det-{i}"
        search_text = html.escape(" ".join(str(c).lower() for c in row))
        selected_cls = " rt-row-selected" if i == 0 else ""

        cells: list[str] = []
        for j, cell in enumerate(row):
            if j == 1 and len(headers) > 1 and headers[1] == "Status":
                cls = _STATUS_BADGE.get(str(cell), "status-warn")
                cells.append(
                    f'<td><span class="status-badge {cls}">{html.escape(str(cell))}</span></td>'
                )
            else:
                cells.append(f'<td class="rt-cell">{html.escape(str(cell))}</td>')

        body_parts.append(
            f'<tr class="rt-row{selected_cls}" onclick="rtSelect(this,\'{det_id}\')"'
            f" onkeydown=\"if(event.key==='Enter'||event.key===' ')"
            f"{{event.preventDefault();rtSelect(this,'{det_id}')}}\""
            f' role="button" tabindex="0"'
            f' data-det="{det_id}" data-search="{search_text}">'
            f"{''.join(cells)}"
            f"</tr>"
        )

        detail_html = render_result_detail(record, element_prefix=det_id)
        active_cls = " rt-det-active" if i == 0 else ""
        detail_parts.append(
            f'<div class="rt-det-item{active_cls}" id="{det_id}">{detail_html}</div>'
        )

    n = len(result_table.rows)
    count_text = f"{n} result{'s' if n != 1 else ''}"

    return (
        f'<div class="rt-split-wrap">'
        f'<div class="rt-master">'
        f'<div class="rt-toolbar">'
        f'<input class="rt-search" type="search" placeholder="Search…"'
        f' oninput="rtFilter(this)">'
        f'<span class="rt-count">{count_text}</span>'
        f"</div>"
        f'<div class="rt-table-scroll">'
        f'<table class="rt">'
        f"<thead><tr>{head_cells}</tr></thead>"
        f"<tbody>{''.join(body_parts)}</tbody>"
        f"</table>"
        f"</div>"
        f"</div>"
        f'<aside class="rt-detail-pane">'
        f'<div class="rt-detail-header">Selected Record</div>'
        f'<div class="rt-detail-content">{"".join(detail_parts)}</div>'
        f"</aside>"
        f"</div>"
    )
