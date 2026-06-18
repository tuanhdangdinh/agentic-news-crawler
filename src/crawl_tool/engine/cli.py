"""CLI entry point — argparse dispatch to the agent loop."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import structlog

from crawl_tool.engine.agent import CrawlState
from crawl_tool.engine.config import MAX_DEPTH_CEILING
from crawl_tool.engine.contract import CrawlRequest
from crawl_tool.engine.logging_config import configure_logging
from crawl_tool.engine.output import serialize_payload
from crawl_tool.engine.prompt_parser import PromptParseError, parse_crawl_prompt
from crawl_tool.engine.runner import execute

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
    parser.add_argument("url", nargs="?", default=None, help="Seed URL to crawl")
    parser.add_argument(
        "--prompt",
        default="",
        help="One-shot natural-language crawl description; fills fields not given explicitly",
    )
    parser.add_argument("--goal", default=None, help="Natural-language crawl goal")
    parser.add_argument("--extract-prompt", default=None, help="What to extract from each page")
    parser.add_argument("--extract-schema", default="", help="Path to JSON Schema file")
    parser.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help=f"Maximum crawl depth (default: 1, ceiling: {MAX_DEPTH_CEILING})",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum pages to crawl (default: 100)",
    )
    parser.add_argument(
        "--token-budget",
        type=int,
        default=500_000,
        help="Total token budget (default: 500000)",
    )
    parser.add_argument(
        "--date-filter",
        default=None,
        help="Natural-language date filter, e.g. 'last 7 days'",
    )
    parser.add_argument(
        "--include-undated",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include pages with no detectable date",
    )
    parser.add_argument(
        "--css-selector", default="", help="CSS selector to restrict page content extraction"
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=0,
        help="Truncate page markdown to this many chars before sending to Claude (0 = no limit)",
    )
    parser.add_argument("--same-domain", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--include-pattern", action="append", default=None, metavar="PATTERN")
    parser.add_argument("--exclude-pattern", action="append", default=None, metavar="PATTERN")
    parser.add_argument(
        "--output", default="output.json", help="Output file path (default: output.json)"
    )
    parser.add_argument("--format", choices=["json", "jsonl"], default="json")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser


async def run(args: argparse.Namespace) -> None:
    """Run the crawler from parsed command-line arguments.

    Args:
        args: Parsed CLI arguments from build_parser.
    """
    configure_logging(args.verbose)

    parsed: dict = {}
    if args.prompt:
        try:
            parsed = await parse_crawl_prompt(args.prompt)
        except PromptParseError as exc:
            logger.error("could not parse prompt", error=str(exc))
            return

    seed_url = args.url or parsed.get("seed_url")
    if not seed_url:
        logger.error("no seed url provided (pass a url, or include one in --prompt)")
        return

    def pick(arg_name: str, parsed_name: str, fallback):
        explicit = getattr(args, arg_name)
        return explicit if explicit is not None else parsed.get(parsed_name, fallback)

    goal = pick("goal", "goal", "")
    extract_prompt = pick("extract_prompt", "extract_prompt", "")
    max_depth = pick("max_depth", "max_depth", 1)
    max_pages = pick("max_pages", "max_pages", 100)
    date_filter = pick("date_filter", "date_filter", "")
    include_undated = pick("include_undated", "include_undated", False)
    same_domain = pick("same_domain", "same_domain", True)
    include_patterns = pick("include_pattern", "include_patterns", [])
    exclude_patterns = pick("exclude_pattern", "exclude_patterns", [])

    if not 0 <= max_depth <= MAX_DEPTH_CEILING:
        logger.error(
            "max-depth out of range",
            max_depth=max_depth,
            ceiling=MAX_DEPTH_CEILING,
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
        seed_url=seed_url,
        goal=goal,
        extract_prompt=extract_prompt,
        extract_schema=extract_schema,
        max_depth=max_depth,
        max_pages=max_pages,
        token_budget=args.token_budget,
        same_domain=same_domain,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        date_filter=date_filter,
        include_undated=include_undated,
        css_selector=args.css_selector,
        max_chars=args.max_chars,
    )

    logger.info(
        "running crawl",
        seed_url=seed_url,
        goal=goal or None,
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
