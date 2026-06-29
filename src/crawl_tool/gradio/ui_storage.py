"""Storage page — MinIO stats, object list, delete, and DuckDB query."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from uuid import uuid4

import gradio as gr
import httpx

from crawl_tool.gradio.client import (
    delete_stored_result,
    download_from_storage,
    get_storage_overview,
    query_history,
)


def _format_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string.

    Args:
        size_bytes: Number of bytes.

    Returns:
        Human-readable size string, e.g. "1.0 KB".
    """
    if size_bytes >= 1_073_741_824:
        return f"{size_bytes / 1_073_741_824:.1f} GB"
    if size_bytes >= 1_048_576:
        return f"{size_bytes / 1_048_576:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def _build_stats_html(overview: dict) -> str:
    """Render bucket statistics as chip HTML.

    Args:
        overview: Storage overview dict with total_files, total_size_bytes, last_modified.

    Returns:
        HTML string with stat chips.
    """
    total_files = overview.get("total_files", 0)
    total_size = _format_size(overview.get("total_size_bytes", 0))
    last_mod = overview.get("last_modified") or "—"
    if last_mod != "—":
        last_mod = last_mod[:10]  # date portion only
    return (
        '<div class="chip-list">'
        f'<span class="chip">Files: {total_files}</span>'
        f'<span class="chip">Size: {total_size}</span>'
        f'<span class="chip">Last crawl: {last_mod}</span>'
        "</div>"
    )


def build_storage_page() -> tuple[gr.Column, object, gr.HTML, gr.Dataframe]:
    """Build the storage page as a hideable column."""
    with gr.Column(visible=False) as col:

        # ── Panel 1: Bucket stats ────────────────────────────────────────
        gr.Markdown("### Bucket overview")
        stats_html = gr.HTML("<div class='chip-list'><span class='chip'>Loading…</span></div>")
        refresh_btn = gr.Button("Refresh", size="sm")

        # ── Panel 2: Object list ─────────────────────────────────────────
        gr.Markdown("### Stored results")
        objects_table = gr.Dataframe(
            headers=["job_id", "size", "last_modified"],
            label="Objects",
            interactive=False,
        )

        with gr.Row():
            dl_job_id = gr.Textbox(label="Job ID to download", placeholder="Paste from table above")
            dl_fmt = gr.Radio(["json", "jsonl"], value="json", label="Format")
            dl_btn = gr.Button("Download")
        dl_file = gr.File(label="Downloaded result", visible=False)

        gr.Markdown("---")
        with gr.Row():
            del_job_id = gr.Textbox(label="Job ID to delete", placeholder="Paste from table above")
            del_btn = gr.Button("Delete", variant="stop")
        with gr.Group(visible=False) as confirm_group:
            del_confirm_msg = gr.Markdown("")
            with gr.Row():
                del_cancel_btn = gr.Button("Cancel")
                del_confirm_btn = gr.Button("Confirm delete", variant="stop")
        del_status = gr.Markdown("")

        # ── Panel 3: DuckDB query ────────────────────────────────────────
        gr.Markdown("### Query history")
        with gr.Row():
            hist_seed = gr.Textbox(label="Seed URL", placeholder="e.g. vietnamnet.vn", scale=2)
            hist_goal = gr.Textbox(label="Goal", placeholder="e.g. finance news", scale=2)
            hist_limit = gr.Number(label="Limit", value=20, precision=0, scale=1)
        with gr.Row():
            hist_date_from = gr.Textbox(label="Date from (YYYY-MM-DD)", scale=1)
            hist_date_to = gr.Textbox(label="Date to (YYYY-MM-DD)", scale=1)
            hist_search_btn = gr.Button("Search", variant="primary", scale=1)
        hist_msg = gr.Markdown("")
        hist_table = gr.Dataframe(
            headers=["job_id", "seed_url", "goal", "generated_at", "total_pages"],
            label="Past Crawl Runs",
            interactive=False,
        )
        with gr.Row():
            hist_dl_id = gr.Textbox(label="Job ID to download", placeholder="Paste job_id from table")
            hist_dl_fmt = gr.Radio(["json", "jsonl"], value="json", label="Format")
            hist_dl_btn = gr.Button("Download")
        hist_dl_file = gr.File(label="Downloaded result", visible=False)

        # ── Event handlers ───────────────────────────────────────────────
        async def _load_overview():
            try:
                overview = await get_storage_overview()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 503:
                    return (
                        "<div class='error-text'>Object storage not configured on the engine.</div>",
                        [],
                    )
                return (f"<div class='error-text'>Error: {exc}</div>", [])
            except httpx.RequestError as exc:
                return (f"<div class='error-text'>Engine unreachable: {exc}</div>", [])
            html = _build_stats_html(overview)
            rows = [
                [o["job_id"], _format_size(o["size_bytes"]), o["last_modified"][:19]]
                for o in overview.get("objects", [])
            ]
            return html, rows

        async def _on_download(job_id: str, fmt: str):
            if not job_id.strip():
                return gr.update(visible=False)
            try:
                data = await download_from_storage(job_id.strip(), fmt)
            except httpx.HTTPStatusError as exc:
                raise gr.Error(f"Download failed: {exc.response.status_code}") from exc
            suffix = ".jsonl" if fmt == "jsonl" else ".json"
            path = str(Path(tempfile.gettempdir()) / f"crawl-{uuid4().hex}{suffix}")
            await asyncio.to_thread(Path(path).write_bytes, data)
            return gr.update(value=path, visible=True)

        def _on_delete_click(job_id: str):
            if not job_id.strip():
                return gr.update(visible=False), gr.update(value="")
            msg = f"**Delete `crawl-{job_id.strip()}.json`? This cannot be undone.**"
            return gr.update(visible=True), gr.update(value=msg)

        async def _on_delete_confirm(job_id: str):
            try:
                await delete_stored_result(job_id.strip())
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                msg = "Not found." if status == 404 else f"Error {status}."
                return gr.update(visible=False), gr.update(value=f"**{msg}**"), "", gr.update()
            overview = await get_storage_overview()
            rows = [
                [o["job_id"], _format_size(o["size_bytes"]), o["last_modified"][:19]]
                for o in overview.get("objects", [])
            ]
            return (
                gr.update(visible=False),
                gr.update(value=f"Deleted `crawl-{job_id.strip()}.json`."),
                "",
                rows,
            )

        async def _on_search(seed_url, goal, date_from, date_to, limit):
            result = await query_history({
                "seed_url": seed_url or "",
                "goal": goal or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
                "limit": int(limit or 20),
            })
            if "error" in result:
                return [], f"**Error:** {result['error']}"
            rows = [
                [r["job_id"], r["seed_url"], r["goal"], r["generated_at"], r["total_pages"]]
                for r in result.get("results", [])
            ]
            return rows, f"{len(rows)} result(s) found." if rows else "No results found."

        refresh_btn.click(fn=_load_overview, outputs=[stats_html, objects_table])
        dl_btn.click(fn=_on_download, inputs=[dl_job_id, dl_fmt], outputs=[dl_file])
        del_btn.click(
            fn=_on_delete_click, inputs=[del_job_id], outputs=[confirm_group, del_confirm_msg]
        )
        del_cancel_btn.click(fn=lambda: gr.update(visible=False), outputs=[confirm_group])
        del_confirm_btn.click(
            fn=_on_delete_confirm,
            inputs=[del_job_id],
            outputs=[confirm_group, del_status, del_job_id, objects_table],
        )
        hist_search_btn.click(
            fn=_on_search,
            inputs=[hist_seed, hist_goal, hist_date_from, hist_date_to, hist_limit],
            outputs=[hist_table, hist_msg],
        )
        hist_dl_btn.click(fn=_on_download, inputs=[hist_dl_id, hist_dl_fmt], outputs=[hist_dl_file])

    return col, _load_overview, stats_html, objects_table
