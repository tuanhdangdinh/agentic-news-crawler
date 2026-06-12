"""CLI entry point — argparse dispatch to the agent loop."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import structlog

from crawl_engine.agent import CrawlState
from crawl_engine.config import MAX_DEPTH_CEILING
from crawl_engine.contract import CrawlRequest
from crawl_engine.logging_config import configure_logging
from crawl_engine.output import serialize_payload
from crawl_engine.runner import execute

logger = structlog.get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Returns:
        Configured argparse parser for the crawl-tool CLI.
    """
    parser = argparse.ArgumentParser(
        prog="crawl-tool",
        description="Agent-driven LLM crawler with structured extraction.",
    )
    parser.add_argument("url", help="Seed URL to crawl")
    parser.add_argument("--goal", default="", help="Natural-language crawl goal")
    parser.add_argument("--extract-prompt", default="", help="What to extract from each page")
    parser.add_argument("--extract-schema", default="", help="Path to JSON Schema file")
    parser.add_argument("--max-depth", type=int, default=1, help=f"Maximum crawl depth (default: 1, ceiling: {MAX_DEPTH_CEILING})")
    parser.add_argument("--max-pages", type=int, default=100, help="Maximum pages to crawl (default: 100)")
    parser.add_argument("--token-budget", type=int, default=500_000, help="Total token budget (default: 500000)")
    parser.add_argument("--date-filter", default="", help="Natural-language date filter, e.g. 'last 7 days'")
    parser.add_argument("--include-undated", action="store_true", help="Include pages with no detectable date")
    parser.add_argument("--css-selector", default="", help="CSS selector to restrict page content extraction")
    parser.add_argument("--max-chars", type=int, default=0, help="Truncate page markdown to this many chars before sending to Claude (0 = no limit)")
    parser.add_argument("--same-domain", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-pattern", action="append", default=[], metavar="PATTERN")
    parser.add_argument("--exclude-pattern", action="append", default=[], metavar="PATTERN")
    parser.add_argument("--output", default="output.json", help="Output file path (default: output.json)")
    parser.add_argument("--format", choices=["json", "jsonl"], default="json")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser


async def run(args: argparse.Namespace) -> None:
    """Run the crawler from parsed command-line arguments.

    Args:
        args: Parsed CLI arguments from build_parser.
    """
    configure_logging(args.verbose)

    if not 0 <= args.max_depth <= MAX_DEPTH_CEILING:
        logger.error(
            "max-depth out of range", max_depth=args.max_depth, ceiling=MAX_DEPTH_CEILING
        )
        return

    extract_schema = None
    if args.extract_schema:
        schema_path = Path(args.extract_schema)
        if not await asyncio.to_thread(schema_path.exists):
            logger.error("extract schema file not found", path=args.extract_schema)
            return
        schema_text = await asyncio.to_thread(schema_path.read_text, encoding="utf-8")
        extract_schema = json.loads(schema_text)

    request = CrawlRequest(
        seed_url=args.url,
        goal=args.goal,
        extract_prompt=args.extract_prompt,
        extract_schema=extract_schema,
        max_depth=args.max_depth,
        max_pages=args.max_pages,
        token_budget=args.token_budget,
        same_domain=args.same_domain,
        include_patterns=args.include_pattern,
        exclude_patterns=args.exclude_pattern,
        date_filter=args.date_filter,
        include_undated=args.include_undated,
        css_selector=args.css_selector,
        max_chars=args.max_chars,
    )

    logger.info(
        "running crawl",
        seed_url=args.url,
        goal=args.goal or None,
    )
    payload = await execute(request, CrawlState())

    fmt = args.format
    await asyncio.to_thread(
        Path(args.output).write_text,
        serialize_payload(payload, fmt),
        encoding="utf-8",
    )
    logger.info(
        "crawl done",
        pages=payload["meta"]["total_pages"],
        output=args.output,
    )


def main() -> None:
    """Parse CLI arguments and run the async crawler entry point."""
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
