"""CLI entry point — argparse dispatch to the agent loop."""

import argparse
import asyncio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crawl-tool",
        description="Agent-driven LLM crawler with structured extraction.",
    )
    parser.add_argument("url", help="Seed URL to crawl")
    parser.add_argument("--goal", default="", help="Natural-language crawl goal")
    parser.add_argument("--extract-prompt", default="", help="What to extract from each page")
    parser.add_argument("--extract-schema", default="", help="Path to JSON Schema file for extraction")
    parser.add_argument("--max-depth", type=int, default=1, help="Maximum crawl depth (default: 1)")
    parser.add_argument("--max-pages", type=int, default=1000, help="Maximum pages to crawl (default: 1000)")
    parser.add_argument("--date-filter", default="", help="Natural-language date filter, e.g. 'last 7 days'")
    parser.add_argument("--include-undated", action="store_true", help="Include pages with no detectable date")
    parser.add_argument("--same-domain", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-pattern", action="append", default=[], metavar="PATTERN")
    parser.add_argument("--exclude-pattern", action="append", default=[], metavar="PATTERN")
    parser.add_argument("--output", default="output.json", help="Output file path (default: output.json)")
    parser.add_argument("--format", choices=["json", "jsonl"], default="json")
    return parser


async def run(args: argparse.Namespace) -> None:
    # Week 2: replaced with direct crawler call
    # Week 3+: replaced with agent loop
    print(f"[crawl-tool] seed={args.url} depth={args.max_depth} output={args.output}")
    print("Agent loop not yet implemented — complete week 2 tasks first.")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
