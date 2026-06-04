# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.11 CLI crawler. `main.py` is the command-line entry point. Core code lives in `src/`: `agent.py` runs the LLM crawl loop, `crawler.py` wraps Crawl4AI, `extractor.py` handles structured extraction, `date_filter.py` parses and detects dates, `output.py` writes JSON/JSONL, and shared Pydantic models belong in `src/models/`. Prompt templates are in `prompts/`. Tests live in `tests/`, while project specs, style guides, and reports are under `docs/`.

## Build, Test, and Development Commands

Use `uv` for all dependency and command execution.

- `uv sync` installs project dependencies.
- `uv run playwright install chromium` installs the browser required by Crawl4AI.
- `uv run python main.py <url> --goal "collect economy news" --max-pages 5` runs a local crawl.
- `uv run ruff check .` runs lint checks.
- `uv run ruff format .` formats code.
- `uv run pytest` runs the test suite.

## Required Standards

Before changing code or documentation, read and follow the relevant standards:

- Code changes must follow `docs/standards/coding_style.md`.
- Documentation changes must follow `docs/standards/doc_style.md`.
- If this file and a standards document conflict, the standards document is the source of truth.
- Keep changes scoped to the task. Do not clean up unrelated files, add unrequested features, or refactor surrounding code unless the task asks for it.
- Preserve historical context in reports. When a later implementation changes an older report's context, label it as a revision or post-week note instead of rewriting the report as if it was originally written that way.

## Coding Style & Naming Conventions

Follow `docs/standards/coding_style.md` exactly. Key rules: Python 3.11, Ruff line length 100, lint rules `E/F/I/UP/B/SIM`, explicit public function return types, `X | Y` unions, and built-in generics such as `list[str]`. Keep modules focused: crawler fetches, agent decides, extractor extracts, output serializes. Shared domain types used across modules should live in `src/models/` and be re-exported from `src/models/__init__.py`.

Use structured logging as defined in the coding style guide. Do not introduce direct stdlib `logging` imports in source modules unless the standards document explicitly allows it.

## Documentation Style

Follow `docs/standards/doc_style.md` for every Markdown file under `docs/`.

- Keep report headers, revision history, section order, heading levels, spacing, tables, and code fences consistent with the guide.
- Use one blank line around headings, lists, tables, code fences, and horizontal rules.
- Use `---` only between top-level `##` sections.
- Every code block must include a language tag.

## Testing Guidelines

Tests use `pytest` with `pytest-asyncio`. Name test files `tests/test_<module>.py` and test public behavior, not private helpers directly. Mock external APIs and network-dependent behavior in unit tests. Keep live crawl checks as smoke or integration tests so the default suite does not require API keys or real websites.

## Commit & Pull Request Guidelines

Recent history uses short conventional-style messages such as `feat: implement week 4 extraction` and `docs: remove week 4 planning notes`. Prefer `feat:`, `fix:`, `docs:`, `test:`, or `refactor:` with an imperative summary. Pull requests should describe the user-facing change, list verification commands run, call out skipped tests, and link related issues or planning docs when available.

## Security & Configuration Tips

Never commit `.env`, API keys, cookies, or crawl credentials. Read secrets from environment variables such as `ANTHROPIC_API_KEY`. Keep generated crawl outputs out of Git unless they are intentional fixtures under `tests/fixtures/`.
