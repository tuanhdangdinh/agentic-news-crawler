"""Tests for the preloaded UI development launcher."""

from crawl_gradio.dev_ui import DEV_UI_CSS, DEV_UI_HEAD


def test_dev_ui_css_marks_rows_as_clickable_with_accent_border():
    assert ".rt-row" in DEV_UI_CSS
    assert "cursor: pointer" in DEV_UI_CSS
    assert ".rt-row:hover" in DEV_UI_CSS
    assert ".rt-row-selected" in DEV_UI_CSS
    assert "outline: 2px solid #c94f2d" in DEV_UI_CSS


def test_dev_ui_head_installs_result_handlers_in_page_scope():
    assert DEV_UI_HEAD.startswith("<script>")
    assert "window.rtSelect" in DEV_UI_HEAD
    assert "window.rtFilter" in DEV_UI_HEAD
    assert "window.rtToggleFigure" in DEV_UI_HEAD
    assert "window.rtShowFigures" in DEV_UI_HEAD
    assert "aria-expanded" in DEV_UI_HEAD
    assert DEV_UI_HEAD.endswith("</script>")
