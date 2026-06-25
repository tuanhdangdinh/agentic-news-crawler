"""DuckDB-based query runner for crawl result history stored in MinIO."""

from __future__ import annotations

import asyncio

import duckdb
import structlog

from crawl_tool.engine.contract import CrawlQuery, CrawlSummary
from crawl_tool.engine.storage import StorageSettings

logger = structlog.get_logger(__name__)

_COLS = ["job_id", "seed_url", "goal", "generated_at", "total_pages", "successful", "failed"]


def _configure_s3(conn: duckdb.DuckDBPyConnection, settings: StorageSettings) -> None:
    conn.execute("INSTALL httpfs")
    conn.execute("LOAD httpfs")
    conn.execute("SET s3_region='us-east-1'")
    conn.execute("SET s3_url_style='path'")
    conn.execute(f"SET s3_endpoint='{settings.endpoint}'")
    conn.execute(f"SET s3_access_key_id='{settings.access_key}'")
    conn.execute(f"SET s3_secret_access_key='{settings.secret_key}'")
    conn.execute(f"SET s3_use_ssl={'true' if settings.secure else 'false'}")


def _execute_query(
    conn: duckdb.DuckDBPyConnection, path: str, query: CrawlQuery
) -> list[dict]:
    conditions: list[str] = []
    params: list[str | int] = []

    if query.seed_url:
        conditions.append(
            "LOWER(CAST(meta.seed_url AS VARCHAR)) LIKE LOWER(CONCAT('%', ?, '%'))"
        )
        params.append(query.seed_url)
    if query.goal:
        conditions.append(
            "LOWER(CAST(meta.goal AS VARCHAR)) LIKE LOWER(CONCAT('%', ?, '%'))"
        )
        params.append(query.goal)
    if query.date_from:
        conditions.append("meta.generated_at >= ?")
        params.append(query.date_from)
    if query.date_to:
        conditions.append("meta.generated_at <= ?")
        params.append(query.date_to)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(query.limit)

    sql = f"""
        SELECT
            CAST(meta.job_id AS VARCHAR)                        AS job_id,
            CAST(meta.seed_url AS VARCHAR)                      AS seed_url,
            CAST(meta.goal AS VARCHAR)                          AS goal,
            strftime(meta.generated_at, '%Y-%m-%dT%H:%M:%SZ')  AS generated_at,
            CAST(meta.total_pages AS INTEGER)                   AS total_pages,
            CAST(meta.successful AS INTEGER)                    AS successful,
            CAST(meta.failed AS INTEGER)                        AS failed
        FROM read_json('{path}')
        {where}
        LIMIT ?
    """
    rows = conn.execute(sql, params).fetchall()
    return [dict(zip(_COLS, row, strict=True)) for row in rows]


def _run_query_sync(query: CrawlQuery, settings: StorageSettings) -> list[dict]:
    conn = duckdb.connect()
    _configure_s3(conn, settings)
    path = f"s3://{settings.bucket}/crawl-*.json"
    return _execute_query(conn, path, query)


async def run_query(query: CrawlQuery, settings: StorageSettings) -> list[CrawlSummary]:
    """Run a structured query against crawl result history in MinIO."""
    rows = await asyncio.to_thread(_run_query_sync, query, settings)
    return [CrawlSummary(**row) for row in rows]
