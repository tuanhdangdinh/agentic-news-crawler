# Design: One-Shot Natural Language Prompt for Crawler Configuration

**Prepared:** 2026-06-17

---

## Overview

Today the CLI and HTTP API require explicit structured arguments (`--url`, `--goal`, `--max-pages`,
`--date-filter`, ...). This adds a single natural-language entry point: the user supplies one string
describing the whole crawl, and a Haiku call parses it into the same structured fields before the crawl
starts. Explicit structured arguments, where supplied, always take precedence over what the parser
extracted — the natural-language prompt is a convenience default-filler, not a replacement for the
existing contract.

This follows the same shape as the existing `infer_schema()` in `engine/extractor.py`: a Jinja2 template
rendered to a user message, sent to Haiku, parsed as JSON, and validated.

---

## Architecture

```text
CLI                                          HTTP API
----                                         --------
build_parser() — url optional, --prompt      CrawlRequest.prompt: str | None
       │                                            │
       ▼                                            ▼
run(args)                                    POST /crawl handler
       │ if args.prompt:                            │ if request.prompt:
       ▼                                            ▼
       parse_crawl_prompt(prompt)  ──────────────────
                  │
                  ▼
       engine/prompt_parser.py
                  │ Jinja2 render (parse_prompt.j2) → Haiku → JSON → validate
                  ▼
       dict of only the fields the prompt actually specified
                  │
                  ▼
       merge: explicit field (CLI flag passed / JSON key present) wins,
              else parsed value, else existing default
                  │
                  ▼
       CrawlRequest → AgentConfig → execute()
```

---

## New Module: `engine/prompt_parser.py`

```python
class PromptParseError(Exception):
    """Raised when the prompt cannot be parsed into a usable seed_url."""


async def parse_crawl_prompt(
    prompt: str, client: anthropic.AsyncAnthropic | None = None
) -> dict:
    """Parse a natural-language crawl description into structured fields.

    Returns a dict containing only the keys the prompt actually specified evidence
    for — fields the model found no mention of are omitted, not defaulted. Possible
    keys: seed_url, goal, extract_prompt, max_depth, max_pages, date_filter,
    include_undated, same_domain, include_patterns, exclude_patterns.

    Raises:
        PromptParseError: no usable seed_url found, or the response is not valid JSON
            / fails schema validation.
    """
```

Implementation mirrors `infer_schema`:

1. Render `engine/prompts/parse_prompt.j2` with `prompt`.
2. Call `client.messages.create(model=MODEL, ...)` (Haiku, the existing default `MODEL` from
   `engine/config.py`).
3. Strip markdown fences (reuse `extractor._strip_fences`, or duplicate the one-line helper to avoid a
   cross-module import — duplicate is preferred here since `_strip_fences` is private to `extractor.py`).
4. `json.loads` the result. On `JSONDecodeError` → `PromptParseError`.
5. Validate against a small inline JSON Schema (object with the keys above, correct types). On
   `jsonschema.ValidationError` → `PromptParseError`.
6. If `seed_url` is present, check it has a URL shape (`urllib.parse.urlparse` produces a non-empty
   `scheme` and `netloc`; the template instructs the model to always include the scheme). If `seed_url`
   is absent or fails this check → `PromptParseError("no valid seed URL found in prompt")`.
7. Return the dict as-is (only keys the model included).

No caching (unlike `infer_schema`) — one-shot prompts are not expected to repeat verbatim.

### Template: `engine/prompts/parse_prompt.j2`

Instructs Haiku to:

- Extract only fields explicitly evidenced in the text; omit a key entirely rather than guess a default.
- Always include the URL scheme in `seed_url` (add `https://` if the user wrote a bare domain).
- Keep `goal` and `extract_prompt` as natural-language strings, copied/lightly cleaned from the prompt —
  no summarization that drops user intent.
- Keep `date_filter` as a natural-language fragment (e.g. `"last 7 days"`) — it is re-parsed later by
  `engine/date_filter.py`, not resolved here.
- `max_depth`/`max_pages` are integers; `include_undated`/`same_domain` are booleans;
  `include_patterns`/`exclude_patterns` are arrays of strings.
- Respond with raw JSON only, no markdown fences, no explanation.

---

## CLI Changes (`engine/cli.py`)

```python
parser.add_argument("url", nargs="?", default=None, help="Seed URL to crawl")
parser.add_argument("--prompt", default="", help="One-shot natural-language crawl description")
parser.add_argument("--goal", default=None, ...)
parser.add_argument("--extract-prompt", default=None, ...)
parser.add_argument("--max-depth", type=int, default=None, ...)
parser.add_argument("--max-pages", type=int, default=None, ...)
parser.add_argument("--date-filter", default=None, ...)
parser.add_argument("--include-undated", action=argparse.BooleanOptionalAction, default=None, ...)
parser.add_argument("--same-domain", action=argparse.BooleanOptionalAction, default=None, ...)
parser.add_argument("--include-pattern", action="append", default=None, ...)
parser.add_argument("--exclude-pattern", action="append", default=None, ...)
```

Fields that stay untouched by prompt parsing (`extract_schema`, `token_budget`, `css_selector`,
`max_chars`, `output`, `format`, `verbose`) keep their current concrete defaults.

In `run()`, before building `CrawlRequest`:

```python
parsed: dict = {}
if args.prompt:
    try:
        parsed = await parse_crawl_prompt(args.prompt)
    except PromptParseError as exc:
        logger.error("could not parse prompt", error=str(exc))
        return

def pick(name: str, fallback):
    explicit = getattr(args, name)
    if explicit is not None:
        return explicit
    return parsed.get(name, fallback)

seed_url = args.url or parsed.get("seed_url")
if not seed_url:
    logger.error("no seed url provided (pass a url, or include one in --prompt)")
    return

goal = pick("goal", "")
extract_prompt = pick("extract_prompt", "")
max_depth = pick("max_depth", 1)
max_pages = pick("max_pages", 100)
date_filter = pick("date_filter", "")
include_undated = pick("include_undated", True)
same_domain = pick("same_domain", True)
include_patterns = pick("include_pattern", [])
exclude_patterns = pick("exclude_pattern", [])
```

(Field names above use the argparse `dest` names, e.g. `extract_prompt` for `--extract-prompt`.) The
remaining `CrawlRequest` construction is unchanged, just reading from these resolved locals instead of
`args.*` directly.

`--max-depth` range validation (`MAX_DEPTH_CEILING`) runs against the resolved `max_depth`, after merge.

---

## HTTP API Changes

### `engine/contract.py`

```python
class CrawlRequest(BaseModel):
    seed_url: str = ""
    prompt: str | None = None
    goal: str = ""
    ...  # all other fields unchanged, same defaults as today

    @model_validator(mode="after")
    def _require_seed_or_prompt(self) -> "CrawlRequest":
        if not self.seed_url and not self.prompt:
            raise ValueError("either seed_url or prompt must be provided")
        return self
```

No other field defaults change. `to_agent_config()` is unchanged — by the time it runs, `seed_url` and
every other field already hold their final resolved values (merging happens earlier, in the route
handler, same division of responsibility as the CLI).

### `engine/service.py` — `POST /crawl`

```python
@app.post("/crawl")
async def start_crawl(request: CrawlRequest) -> JobCreated:
    if request.prompt:
        try:
            parsed = await parse_crawl_prompt(request.prompt)
        except PromptParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        for field, value in parsed.items():
            if field not in request.model_fields_set:
                setattr(request, field, value)
        if not request.seed_url:
            raise HTTPException(
                status_code=400, detail="no seed url provided or found in prompt"
            )
    ...
```

`request.model_fields_set` is the set of field names the caller actually included in the incoming JSON
body (Pydantic v2 tracks this regardless of whether the value matched the schema default) — this is what
lets an explicit `"max_pages": 100` in the request body override a parsed value, even though `100` is
also `CrawlRequest`'s own default for that field.

---

## Error Handling

| Situation | CLI | HTTP API |
|---|---|---|
| No url and no prompt | `logger.error`, `run()` returns before any work starts (argparse can't enforce "one of two optional args" at parse time, so this is a runtime check) | Pydantic validation error (422) from `_require_seed_or_prompt` |
| Prompt parse fails (bad JSON / schema) | `logger.error`, `run()` returns without crawling | `HTTPException(400)` |
| Prompt parsed but no seed_url found | `logger.error`, `run()` returns without crawling | `HTTPException(400)` |
| Explicit field + prompt both set | explicit wins | explicit (any field in `model_fields_set`) wins |

No silent fallback to a wrong/empty seed URL in any path — an unusable prompt always stops the crawl
before it starts, never substitutes a guessed default for `seed_url`.

---

## Tests

### `tests/engine/test_prompt_parser.py` (new)

Mocking style matches `tests/engine/test_extractor_infer_schema.py` (patch
`crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic`):

1. Full prompt → all fields present in response → dict contains exactly those keys
2. Markdown-fenced JSON response → fences stripped, parsed correctly
3. Response with only `seed_url` and `goal` → returned dict has only those two keys
4. Bare domain in response (`"vnexpress.net"`, no scheme) → `PromptParseError` (template is expected to
   always add a scheme, so a schemeless `seed_url` from the model is treated as a parse failure, not
   silently fixed up in code)
5. No `seed_url` key in response at all → `PromptParseError`
6. Invalid JSON response → `PromptParseError`
7. JSON valid but fails schema validation (e.g. `max_pages` as a string) → `PromptParseError`

### CLI tests (extend or add `tests/engine/test_cli.py`)

8. `--prompt` only, no positional url → parsed `seed_url` used, `run_agent`/`execute` invoked with it
9. `--prompt "..." --max-pages 20` where the prompt also implies a page count → resolved `max_pages == 20`
10. Positional `url` + `--prompt` (prompt has a different URL) → positional `url` wins
11. Neither `url` nor `--prompt` → no crawl started, clear error logged
12. `--prompt` parse raises `PromptParseError` → no crawl started, clear error logged

### `tests/engine/test_service.py` (extend)

13. `POST /crawl` with only `prompt` set → job created with parsed `seed_url`
14. `POST /crawl` with `prompt` + explicit `max_pages` in the JSON body → resolved request keeps the
    explicit `max_pages`, not the parsed one
15. `POST /crawl` with neither `seed_url` nor `prompt` → 422
16. `POST /crawl` with `prompt` that parses but contains no `seed_url` → 400
17. `POST /crawl` with `prompt` that fails to parse (mocked `PromptParseError`) → 400

---

## Out of Scope

- `extract_schema`, `token_budget`, `css_selector`, `max_chars` are not parsed from natural language —
  these stay explicit-only, per existing design (`--extract-schema` file path / registry / `infer_schema`
  pipeline already covers schema derivation).
- No caching of parsed prompts (unlike `infer_schema`'s `_schema_cache`) — one-shot prompts aren't expected
  to repeat.
- No Gradio UI changes in this design; the HTTP `prompt` field is added so the UI *can* adopt it later,
  but wiring it into `gradio/` is a separate piece of work.
