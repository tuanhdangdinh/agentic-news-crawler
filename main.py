"""CLI entry point — argparse dispatch to the agent loop."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import structlog

from src.agent import AgentConfig, run_agent
from src.crawler import fetch_page
from src.logging_config import configure_logging
from src.output import write_results

logger = structlog.get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crawl-tool",
        description="Agent-driven LLM crawler with structured extraction.",
    )
    parser.add_argument("url", help="Seed URL to crawl")
    parser.add_argument("--goal", default="", help="Natural-language crawl goal")
    parser.add_argument("--extract-prompt", default="", help="What to extract from each page")
    parser.add_argument("--extract-schema", default="", help="Path to JSON Schema file")
    parser.add_argument("--max-depth", type=int, default=1, help="Maximum crawl depth (default: 1)")
    parser.add_argument("--max-pages", type=int, default=100, help="Maximum pages to crawl (default: 100)")
    parser.add_argument("--token-budget", type=int, default=500_000, help="Total token budget (default: 500000)")
    parser.add_argument("--date-filter", default="", help="Natural-language date filter, e.g. 'last 7 days'")
    parser.add_argument("--include-undated", action="store_true", help="Include pages with no detectable date")
    parser.add_argument("--same-domain", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-pattern", action="append", default=[], metavar="PATTERN")
    parser.add_argument("--exclude-pattern", action="append", default=[], metavar="PATTERN")
    parser.add_argument("--output", default="output.json", help="Output file path (default: output.json)")
    parser.add_argument("--format", choices=["json", "jsonl"], default="json")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser


async def run(args: argparse.Namespace) -> None:
    configure_logging(args.verbose)

    extract_schema = None
    if args.extract_schema:
        schema_path = Path(args.extract_schema)
        if not schema_path.exists():
            print(f"[crawl-tool] error: --extract-schema file not found: {args.extract_schema}")
            return
        extract_schema = json.loads(schema_path.read_text(encoding="utf-8"))

    config = AgentConfig(
        goal=args.goal,
        max_depth=args.max_depth,
        max_pages=args.max_pages,
        token_budget=args.token_budget,
        same_domain=args.same_domain,
        include_patterns=args.include_pattern,
        exclude_patterns=args.exclude_pattern,
        extract_prompt=args.extract_prompt,
        extract_schema=extract_schema,
        date_filter=args.date_filter,
        include_undated=args.include_undated,
    )

    print(f"[crawl-tool] seed={args.url}  depth={args.max_depth}  max_pages={args.max_pages}")
    if args.goal:
        print(f"[crawl-tool] goal: {args.goal}")

    if not args.goal and not args.extract_prompt:
        logger.info("running direct single-page fetch")
        page = await fetch_page(args.url)
        print(
            f"  [  1] status={page.status_code} "
            f"chars={len(page.markdown):>6} "
            f"links={len(page.links_internal):>3} "
            f"{args.url}"
        )

        run_meta = {
            "seed_url": args.url,
            "goal": args.goal,
            "max_depth": 0,
            "max_pages": 1,
            "pages_collected": 1 if page.success else 0,
            "urls_visited": 1,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "finish_reason": "single page fetched",
        }
        logger.info("writing output", format=args.format, path=args.output)
        write_results([page], args.output, fmt=args.format, run_meta=run_meta)
        print(f"\n[crawl-tool] done — {1 if page.success else 0} pages  1 visited  0 tokens")
        if page.error:
            print(f"[crawl-tool] fetch error: {page.error}")
        print(f"[crawl-tool] output: {args.output}")
        return

    logger.info("running agent crawl")
    state = await run_agent(args.url, config)

    print(
        f"\n[crawl-tool] done — "
        f"{len(state.pages)} pages  "
        f"{len(state.visited)} visited  "
        f"{state.tokens_used:,} tokens"
    )
    if state.finish_reason:
        print(f"[crawl-tool] finish reason: {state.finish_reason}")

    run_meta = {
        "seed_url": args.url,
        "goal": args.goal,
        "max_depth": args.max_depth,
        "max_pages": args.max_pages,
        "pages_collected": len(state.pages),
        "article_pages_collected": len(state.article_pages),
        "article_pages": state.article_pages,
        "urls_visited": len(state.visited),
        "total_input_tokens": state.total_input_tokens,
        "total_output_tokens": state.total_output_tokens,
        "finish_reason": state.finish_reason,
        "stop_reason": state.stop_reason,
        "frontier_at_finish": state.frontier_at_finish,
    }

    logger.info("writing output", format=args.format, path=args.output)
    write_results(state.pages, args.output, fmt=args.format, run_meta=run_meta)
    print(f"[crawl-tool] output: {args.output}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
