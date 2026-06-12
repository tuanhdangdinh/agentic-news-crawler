"""JSON / JSONL serialization for crawl results."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import structlog

from crawl_engine.models import PageResult

logger = structlog.get_logger(__name__)


def _page_record(page: PageResult) -> dict:
    """Convert a PageResult to a plain dict, dropping html to keep output lean."""
    return page.model_dump(exclude={"html", "raw_markdown"})


def write_json(pages: list[PageResult], path: str, run_meta: dict | None = None) -> None:
    """Write all pages as a single JSON file.

    Args:
        pages: Crawl results to serialize.
        path: Output file path.
        run_meta: Optional crawl-run metadata to include at the top level.
    """
    output = {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "total_pages": len(pages),
            "successful": sum(1 for p in pages if p.success),
            "failed": sum(1 for p in pages if not p.success),
            **(run_meta or {}),
        },
        "pages": [_page_record(p) for p in pages],
    }
    Path(path).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.debug("wrote json", path=path, pages=len(pages))


def write_jsonl(pages: list[PageResult], path: str) -> None:
    """Write one JSON record per line (JSONL format).

    Args:
        pages: Crawl results to serialize.
        path: Output file path.
    """
    lines = [json.dumps(_page_record(p), ensure_ascii=False) for p in pages]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.debug("wrote jsonl", path=path, lines=len(pages))


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
    logger.info(
        "output summary",
        path=path,
        format=fmt,
        total=len(pages),
        successful=sum(1 for page in pages if page.success),
        failed=sum(1 for page in pages if not page.success),
    )
