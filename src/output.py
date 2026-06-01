"""JSON / JSONL serialization for crawl results."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from src.crawler import PageResult


def _page_record(page: PageResult) -> dict:
    """Convert a PageResult to a plain dict, dropping html to keep output lean."""
    d = asdict(page)
    d.pop("html", None)
    d.pop("raw_markdown", None)
    return d


def write_json(pages: list[PageResult], path: str, run_meta: dict | None = None) -> None:
    """Write all pages as a single JSON file.

    Args:
        pages: Crawl results to serialize.
        path: Output file path.
        run_meta: Optional crawl-run metadata to include at the top level.
    """
    output = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_pages": len(pages),
            "successful": sum(1 for p in pages if p.success),
            "failed": sum(1 for p in pages if not p.success),
            **(run_meta or {}),
        },
        "pages": [_page_record(p) for p in pages],
    }
    Path(path).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(pages: list[PageResult], path: str) -> None:
    """Write one JSON record per line (JSONL format).

    Args:
        pages: Crawl results to serialize.
        path: Output file path.
    """
    lines = [json.dumps(_page_record(p), ensure_ascii=False) for p in pages]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_results(
    pages: list[PageResult],
    path: str,
    fmt: str = "json",
    run_meta: dict | None = None,
) -> None:
    """Dispatch to the appropriate writer based on fmt.

    Args:
        pages: Crawl results to serialize.
        path: Output file path.
        fmt: Either "json" or "jsonl".
        run_meta: Optional metadata for JSON mode.
    """
    if fmt == "jsonl":
        write_jsonl(pages, path)
    else:
        write_json(pages, path, run_meta)
