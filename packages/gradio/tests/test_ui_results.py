"""Tests for src/ui_results.py — HTML rendering."""

from crawl_gradio.ui_results import (
    build_result_table,
    render_financial_figures,
    render_result_detail,
    render_result_table_html,
)


def test_render_result_table_html_structure():
    payload = {
        "pages": [
            {
                "url": "https://example.com/1",
                "success": True,
                "metadata": {"extracted": {"title": "Article 1", "author": "John Doe"}},
            },
            {
                "url": "https://example.com/2",
                "success": True,
                "metadata": {"extracted": {"title": "Article 2", "author": "Jane Doe"}},
            },
        ]
    }

    table = build_result_table(payload, mode="Extracted", extraction_requested=True)
    html_output = render_result_table_html(table)

    # Check for split layout markers
    assert "rt-split-wrap" in html_output
    assert "rt-master" in html_output
    assert "rt-detail-pane" in html_output

    # Check for rows and detail items
    assert "rt-row" in html_output
    assert "rt-det-item" in html_output
    assert "Article 1" in html_output
    assert "Article 2" in html_output

    # Check for selection markers
    assert "rt-row-selected" in html_output
    assert "rt-det-active" in html_output
    assert "rtSelect(this,'rt-det-0')" in html_output
    assert 'role="button"' in html_output
    assert 'tabindex="0"' in html_output
    assert "event.key==='Enter'" in html_output
    assert "event.key===' '" in html_output


def test_render_result_table_empty_state():
    table = build_result_table({"pages": []}, mode="Extracted", extraction_requested=True)
    html_output = render_result_table_html(table)
    assert "rt-empty" in html_output
    assert "No pages with successful extraction" in html_output


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
