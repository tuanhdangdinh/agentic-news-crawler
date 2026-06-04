# Coding Style Guide

---

## Tooling

- **Linter/formatter**: Ruff — run `uv run ruff check .` and `uv run ruff format .` before every commit
- **Tests**: run `uv run pytest`
- **Config lives in** `pyproject.toml` — line-length 100, rules E/F/I/UP/B/SIM
- **Package manager**: `uv` only — never `pip install`

---

## Before Writing New Code

- Use **Context7** or **Exa** MCPs before implementing against external libraries or APIs
- Local refactors do not need MCP lookup unless behavior depends on external docs
- Do not rely on training-data knowledge for library APIs — docs drift, training data does not update
- Verify the exact class names, parameter names, and return types from current docs
- If a parameter or method name cannot be confirmed in current docs, look it up — do not guess

---

## Type Hints

- Required on every public function signature
- Use `X | Y` union syntax — not `Optional[X]` or `Union[X, Y]`
- Use `list[str]`, `dict[str, int]` — not `List`, `Dict` from `typing`
- Return type always explicit — no bare `def foo():` on public functions

---

## Async

- All I/O functions must be `async def`
- Use async clients: `AsyncAnthropic`, `AsyncWebCrawler` — never the sync equivalent inside an async context
- Never call blocking I/O inside an async function — it holds the event loop

---

## Imports

- Order: stdlib → third-party → local, each group separated by a blank line
- Ruff `I` rules enforce this automatically
- No wildcard imports (`from x import *`)

---

## Error Handling

- Functions that can fail return a result object — e.g. `PageResult(success=False, error=...)`
- No bare `except Exception: pass` — silent swallowing hides real bugs
- Validate only at system boundaries (user input, external APIs) — trust internal code

---

## Naming and Structure

- Constants: `UPPER_SNAKE_CASE` at module level — no magic numbers inline
- One concern per module — `crawler.py` fetches, `agent.py` decides, `extractor.py` extracts, `src/models/` holds shared domain types
- Add helper abstractions only when they clarify a boundary, reduce real duplication, or isolate external APIs

---

## Modular Design

- Shared domain types belong in `src/models/` when they represent crawler-wide concepts, not in the module that first created them
- Cross-module reuse is a signal to extract a type, but ownership should follow the domain boundary rather than a fixed usage count
- Modules should depend on stable public interfaces; avoid making consumers import implementation details from sibling modules
- Re-export intentionally public package APIs from `__init__.py`, but keep internal helpers private to their modules

---

## Comments

- Only comment the **why** — never the what
- If the code name already explains it, no comment needed
- One short line max — no multi-line comment blocks

---

## Tests

- Unit test guardrails, URL filtering, date parsing, and output serialization
- Mock external APIs in unit tests
- Keep real-site crawl tests as smoke or integration tests
- Do not require live API keys for the default test suite

---

## Secrets

- Never commit `.env`, API keys, cookies, or crawl credentials
- Read secrets from environment variables
- Keep sample values as placeholders only
