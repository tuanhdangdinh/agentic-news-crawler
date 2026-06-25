# Design: News Ranking Engine — Impact and Briefing Modes

**Prepared:** 2026-06-25

**Revision history:**

- Initial draft: unify impact and briefing into one ranking engine behind a general `--prompt`.
- Rev 2: bound rank-mode fanout (rank-specific `max_pages`, job-wide article cap, scoring concurrency limit), account scoring tokens, match article pages on `final_url`, split `filtered_count` into weak vs error counts, constrain `intent` to an enum.

---

## Overview

Today `--prompt` answers one shape of request: "go to this URL and crawl/extract." It always
requires a seed URL (`prompt_parser.py:88`, `cli.py:126`, `service.py:134`). This design generalizes
`--prompt` into the single front door for the crawler and adds a second answer shape: **rank today's
economy/finance news**, returned as a justified, ranked shortlist rather than a flat page dump.

Two user-facing features share one engine:

- **Impact mode** — the user names one or more **targets** (a price, commodity, sector, company,
  indicator). Each article is scored for its impact on each target. Output is sorted by strongest
  impact. Example: *"Which Vietnamese economy news this morning may affect gasoline retail prices and
  global crude oil prices?"*
- **Briefing mode** — the user names **no target**. Each article is scored for general **significance**.
  Output is the TV-morning-rundown of what matters today. Example: *"Give me the hot economy news this
  morning."*

These are not two pipelines. They are **one ranking engine with a pluggable scoring step**; the only
difference is the scoring prompt, and the switch between them is "did the user name a target?". This
collapses what was previously imagined as a separate "vague prompt → ask a clarifying question" branch:
a request with no target is not vague, it is a briefing request.

---

## Architecture

`--prompt` parses into a *plan*. `runner.execute()` dispatches on `plan.intent`. The existing crawl is
just one intent; the ranking engine is another.

```text
--prompt "<anything>"
        │
        ▼
parse_crawl_prompt()  →  plan = { intent, seed_url?, targets?, date_filter?, goal?, ... }
        │                         intent ∈ { "crawl", "rank" }
        ▼
runner.execute()  ── dispatch on intent ──┐
        │                                  │
   intent == "crawl"                  intent == "rank"
        │                                  │
        ▼                                  ▼
  run_agent(seed)                  select_sources(targets)        # sources.py, fixed list (phase 1)
  → _result_payload()                     │
   [unchanged]                            ▼
                              asyncio.gather(run_agent per source)  # parallel multi-source crawl
                                          │
                                          ▼
                              score_article(page, mode, targets)    # ranker.py, one Claude call/article
                              mode = "impact" if targets else "significance"
                                          │ asyncio.gather over article pages
                                          ▼
                              rank_and_filter(scored)                # ranker.py, pure Python sorted()
                                          │
                                          ▼
                              _ranked_payload()                      # runner.py
```

The scoring step is the only place the two modes differ. Crawl, source selection, ranking, and the
output envelope are mode-independent.

---

## The Plan: Parser Changes (`engine/prompt_parser.py`)

`parse_crawl_prompt()` keeps its shape — render template → Haiku → `json.loads` → `jsonschema.validate`,
returning only the keys the prompt gave evidence for. Two fields are added to `_PARSED_PROMPT_SCHEMA`:

| Field | Type | Meaning |
|---|---|---|
| `intent` | `"crawl"` \| `"rank"` | Which pipeline runs. Defaults to `"crawl"` when absent. |
| `targets` | array of strings | Things to score impact against. Present → impact mode; absent/empty → significance mode. |

### Design Decisions

- Classification and field extraction stay a **single** Haiku call — `intent` and `targets` are extra
  keys in the same response, not a separate classifier pass. This matches the existing "one call,
  only-evidenced-keys" contract.
- The scoring **mode is derived, not parsed** — `mode = "impact" if targets else "significance"`. The
  model decides intent and whether targets exist; the runner derives the mode. Keeps the model's job
  to extraction, not policy.
- **The seed-URL guard becomes conditional on intent.** `seed_url` is required only when
  `intent == "crawl"`. For `intent == "rank"`, a missing `seed_url` is normal, not a
  `PromptParseError`. The hard guards at `prompt_parser.py:88`, `cli.py:126`, and `service.py:134` are
  relaxed accordingly (see below).
- For `rank` intent, `targets` is the only rank-specific field the parser must produce; `date_filter`
  flows through the existing natural-language path (e.g. `"this morning"` → resolved later by
  `engine/date_filter.py`).

### Template: `engine/prompts/parse_prompt.j2` (extended)

Add instructions:

- Classify the request as `"crawl"` (the user points at a site / URL and wants pages or extraction) or
  `"rank"` (the user asks which news *matters* — impact on something, or what's important today).
- For `"rank"`, extract `targets` as a list of the specific things the user wants impact judged against
  (prices, commodities, sectors, companies, indicators). If the user asks for important/hot/top news
  with no specific subject, return `intent: "rank"` with `targets` omitted or empty.
- `seed_url` is only expected for `"crawl"`.

---

## New Module: `engine/sources.py`

Selects which URLs an impact/briefing crawl starts from when the user gave no URL.

### Design Decisions

- **Phase 1 is a fixed curated list** of Vietnamese economy/finance section URLs (e.g. the economy /
  finance landing pages of vneconomy, cafef, and similar). This de-risks the whole feature: the
  scoring and ranking pipeline becomes shippable without solving open-ended topic→source mapping.
- **Topic→source selection via LLM is explicitly phase 2.** The interface is designed so it can be
  swapped in later without touching callers.
- `targets` is accepted now but unused for selection in phase 1 — the signature is forward-compatible.

### Public Interface

```python
def select_sources(targets: list[str]) -> list[str]
```

- Returns the list of seed URLs to crawl. In phase 1, returns the curated list regardless of `targets`.
- Never returns an empty list (the curated list is non-empty by construction).

---

## New Module: `engine/ranker.py`

The pluggable scoring step plus the pure-Python rank/filter. This replaces any notion of a separate
per-article "extract facts" stage — the scorer reads page markdown directly and emits the final scored
record, because the ranked output never consumes raw extracted facts (see Out of Scope).

### Design Decisions

- **One Claude call per article**, parallelized with a **bounded** `asyncio.gather`, mirroring the
  `extractor.extract()` pattern (render template → Haiku → `json.loads` → `jsonschema.validate`, never
  raises — returns an error record on failure).
- **Concurrency is capped by a `Semaphore`** (`SCORING_CONCURRENCY`, default 8). Unbounded
  `gather` over every article would fire hundreds of simultaneous Claude calls and hit rate limits
  before any token budget — the cap is a correctness/safety requirement, not a tuning nicety. The
  caller passes **one shared `AsyncAnthropic` client** through the whole gather.
- **`score_article` returns its token usage** alongside the scored record, so the runner can sum
  scoring tokens into the payload (crawl accounting at `agent.py:392-393` covers only the crawl).
- **Pluggable prompt, fixed code path.** `mode` selects `score_impact.j2` vs `score_significance.j2`
  and the validation schema. Everything else is shared.
- **Impact score scale: signed −5..+5** per target — sign encodes direction, magnitude encodes
  strength. A strong negative (e.g. a tariff crushing steel) sorts as high as a strong positive. The
  sort key is `max_abs_impact = max(|score|)` across targets.
- **Significance score scale: 0..5** — one number per article, the sort key directly.
- **Every score carries an `evidence` quote** lifted from the article, making each score auditable.
  Without it a score is unfalsifiable; with it the user can trust or overrule in seconds.
- **Ranking and filtering are pure Python** (`sorted()` + a threshold) — not an LLM step.
- **Filter default: drop articles whose sort key magnitude `< 2`** (module constant, easy to tune).
- **Weak filtering and scoring errors are counted separately**, not merged. Conflating
  "irrelevant article" with "Claude/JSON/API failure" would undermine the not-silently-lossy goal:
  the first is a real ranking outcome, the second is a failure the user should see. `rank_and_filter`
  returns both counts, and the runner surfaces error summaries in `meta` (see payload).

### Public Interface

```python
async def score_article(
    page: PageResult,
    mode: str,                      # "impact" | "significance"
    targets: list[str],             # used by impact mode; ignored by significance mode
    *,
    client: anthropic.AsyncAnthropic,   # shared across the whole gather
    semaphore: asyncio.Semaphore,       # bounds concurrent Claude calls
) -> dict

def rank_and_filter(scored: list[dict]) -> tuple[list[dict], int, list[dict]]
```

- `score_article` returns a scored record (shapes below) on success, or
  `{"error": "<message>", "url": ...}` on parse/validation/API failure. Never raises. Both shapes carry
  a `usage` field (`{"input_tokens": int, "output_tokens": int}`) so the runner can sum scoring tokens.
- `rank_and_filter` returns `(ranked_kept_articles, weak_filtered_count, error_records)` — sorted
  descending by sort key, weak items removed and counted, error records separated out (not silently
  dropped) for the runner to summarize in `meta`.

### Scored record shapes

Impact mode:

```json
{
  "article_title": "...",
  "url": "...",
  "publish_date": "2026-06-25",
  "max_abs_impact": 5,
  "impacts": [
    {"target": "...", "score": 5, "direction": "up", "rationale": "...", "evidence": "..."}
  ]
}
```

Significance mode:

```json
{
  "article_title": "...",
  "url": "...",
  "publish_date": "2026-06-25",
  "significance": 4,
  "rationale": "...",
  "evidence": "..."
}
```

### Templates

- `engine/prompts/score_impact.j2` — given article markdown + `targets`, emit one `impacts[]` entry per
  target with signed score, direction, rationale, evidence.
- `engine/prompts/score_significance.j2` — given article markdown, emit a 0..5 significance with
  rationale and evidence (per-article judgment only; cross-source prominence/clustering is phase 2).

---

## Runner Changes (`engine/runner.py`)

### Design Decisions

- **Dispatch on `intent` explicitly**, replacing the implicit `if not config.goal and not
  config.extract_prompt` heuristic at `runner.py:82` — that heuristic was already an unnamed intent
  check; this names it.
- **Multi-source crawl runs in parallel** via `asyncio.gather`, one `run_agent` per source, each with
  its own `CrawlState`. Results are concatenated. Parallel fits the async-everywhere rule and is
  fastest for N sources.
- **Fanout is bounded on three axes.** Without caps, N sources × `max_pages=100` × a scoring call each
  is unbounded cost and concurrency:
  - **Per-source pages:** rank config uses `RANK_MAX_PAGES` (default 25), not the crawl default of 100.
  - **Job-wide articles scored:** after concatenation, the article list is truncated to
    `RANK_MAX_ARTICLES` (default 60) before scoring, so total scoring calls have a hard ceiling
    regardless of source count.
  - **Scoring concurrency:** the `Semaphore` from `ranker.py` (`SCORING_CONCURRENCY`, default 8).
  - Per-source token budget still applies inside each `run_agent`; these caps bound the rank job *as a
    whole*, which the per-`CrawlState` budget cannot.
- Each per-source `run_agent` uses a synthesized rank config: a goal of "collect today's economy /
  finance article pages", the resolved `date_filter` (defaulting to today for `rank`), `RANK_MAX_PAGES`,
  and **no per-page extraction** (scoring happens after the crawl, not during).
- Article pages to score are the pages whose **`final_url`** is in a source's `state.article_pages`
  — `run_agent` records `page.final_url` there (`agent.py:541`), so matching on `page.url` would drop
  any article that redirected.
- **Token accounting sums crawl + scoring.** The payload's `total_input_tokens`/`total_output_tokens`
  add the per-source crawl totals to the `usage` returned by every `score_article` call.
- **Live progress is coarse for rank jobs (phase 1).** Each source crawls into its own `CrawlState`,
  so the job-level `state` the service polls for `pages_collected` is not updated during a rank run;
  progress reflects 0 until the run completes. Accurate cross-source progress aggregation is phase 2.

### Sketch

```python
async def execute(request: CrawlRequest, state: CrawlState) -> dict:
    ...
    if request.intent == "rank":
        return await _execute_rank(request, state, proxy_rotator)
    # crawl intent: unchanged
    ...

async def _execute_rank(request, state, proxy_rotator) -> dict:
    sources = select_sources(request.targets)
    rank_config = _rank_config(request)            # RANK_MAX_PAGES, extract disabled, date=today
    # run_agent populates a passed-in CrawlState in place, so pre-create one per source.
    states = [CrawlState() for _ in sources]
    await asyncio.gather(*[
        run_agent(src, rank_config, state=st, proxy_rotator=proxy_rotator)
        for src, st in zip(sources, states, strict=True)
    ])
    # Match on final_url (run_agent records final_url in article_pages), then cap job-wide.
    articles = [
        p for st in states for p in st.pages if p.final_url in st.article_pages
    ][:RANK_MAX_ARTICLES]

    mode = "impact" if request.targets else "significance"
    client = anthropic.AsyncAnthropic()
    semaphore = asyncio.Semaphore(SCORING_CONCURRENCY)
    scored = await asyncio.gather(*[
        score_article(p, mode, request.targets, client=client, semaphore=semaphore)
        for p in articles
    ])
    ranked, weak_filtered, errors = rank_and_filter(scored)
    return _ranked_payload(request, mode, ranked, weak_filtered, errors, states, scored)
```

### Ranked payload

```json
{
  "meta": {
    "generated_at": "...",
    "mode": "impact",
    "targets": ["..."],
    "sources_crawled": ["..."],
    "articles_scored": 23,
    "weak_filtered_count": 15,
    "score_error_count": 3,
    "score_errors": [{"url": "...", "error": "..."}],
    "total_input_tokens": 0,
    "total_output_tokens": 0
  },
  "ranked_articles": [ ... ]
}
```

`targets` is present only in impact mode. `weak_filtered_count` is articles dropped below the score
threshold; `score_error_count` and `score_errors` capture scoring failures separately so they are never
silently lost. `total_input_tokens`/`total_output_tokens` sum the per-source crawl totals **and** the
`usage` from every `score_article` call.

---

## CLI and HTTP Changes

The `--prompt` flag and the HTTP `prompt` field already exist and stay as-is — this generalizes what
flows out of the parser, not the entry surface.

### `engine/cli.py`

- The seed-URL guard at `cli.py:126` becomes conditional: error only when `parsed.get("intent",
  "crawl") == "crawl"` and no `seed_url` resolved. For `rank` intent with no URL, proceed.
- Resolve `intent` and `targets` from the parsed dict (no new CLI flags) and pass them into the request.

### `engine/contract.py`

Add to `CrawlRequest`:

```python
intent: Literal["crawl", "rank"] = "crawl"
targets: list[str] = Field(default_factory=list)
```

- **`intent` is a constrained `Literal`, not a bare `str`** — `CrawlRequest` is the public HTTP model,
  so an unconstrained string would let a direct API body like `{"intent": "foo"}` pass validation and
  fall through to the crawl path. `Literal` (or a `str` Enum, matching `JobStatus`) makes the API reject
  it. The values match the parser's `intent` schema.
- Update `_require_seed_url_or_prompt`: `seed_url` is required for `intent == "crawl"` only; `rank`
  requests are valid without a `seed_url`.
- `to_agent_config()` is unchanged — `intent`/`targets` are read by the runner's dispatch, not by
  `AgentConfig`.

### `engine/service.py` — `POST /crawl`

- After parsing the prompt and merging fields (existing loop at `service.py:131`), the seed-URL check at
  `service.py:134` becomes conditional on `request.intent == "crawl"`. A `rank` request with no
  `seed_url` is accepted and dispatched.

---

## Error Handling

| Situation | Behaviour |
|---|---|
| `crawl` intent, no seed URL | unchanged — CLI logs and returns; HTTP 400 / 422 |
| `rank` intent, no seed URL | normal — sources come from `select_sources()` |
| Prompt parse fails (bad JSON / schema) | unchanged — CLI returns; HTTP 400 |
| One article's `score_article` fails | error record separated into `score_errors`, counted in `score_error_count`; crawl continues |
| All articles weak | empty `ranked_articles` with `weak_filtered_count` equal to articles scored — valid result, not an error |
| `select_sources` returns the curated list | always non-empty in phase 1 |

`score_article` never raises (matches `extractor.extract`), so one bad page never sinks a ranking run.

---

## Tests

### `tests/engine/test_prompt_parser.py` (extend)

1. Prompt naming targets → `intent == "rank"`, `targets` populated, no `seed_url` required.
2. "hot economy news this morning" → `intent == "rank"`, `targets` empty/absent.
3. Prompt with a URL → `intent == "crawl"`, `seed_url` present (existing behaviour preserved).
4. `rank` intent with no `seed_url` → **no** `PromptParseError` (guard relaxation).

### `tests/engine/test_ranker.py` (new)

Mock `crawl_tool.engine.ranker.anthropic.AsyncAnthropic`, matching `test_extractor_*` style.

5. Impact mode, two targets → record has one `impacts[]` entry per target and correct `max_abs_impact`.
6. Significance mode → record has a 0..5 `significance`, `rationale`, `evidence`; no `impacts`.
7. Malformed Claude JSON → error record returned, never raises.
8. `rank_and_filter` drops sort-key `< 2`, sorts descending, returns correct `weak_filtered_count`.
9. `rank_and_filter` separates error records from weak ones — `error_records` and `weak_filtered_count`
   are counted independently, error records never appear in the ranked list.
10. `score_article` returns a `usage` field on both success and error records.

### `tests/engine/test_sources.py` (new)

11. `select_sources([...])` returns the non-empty curated list regardless of `targets`.

### `tests/engine/test_runner.py` (extend or new)

12. `intent == "rank"` dispatches `_execute_rank`, gathers `run_agent` per source, scores article pages
    (matched on `final_url`), returns a `ranked_articles` payload (all collaborators mocked).
13. Job-wide cap: more than `RANK_MAX_ARTICLES` article pages collected → only `RANK_MAX_ARTICLES` scored.
14. Redirected article (`page.url != page.final_url`, `final_url` in `article_pages`) is still scored.
15. Payload `total_*_tokens` equals crawl totals plus summed `score_article` usage.
16. `intent == "crawl"` path unchanged.

### `tests/engine/test_service.py` (extend)

17. `POST /crawl` with a `rank` prompt and no `seed_url` → job created (no 400).
18. `POST /crawl` with a `crawl` prompt and no resolvable `seed_url` → 400 (unchanged).
19. `POST /crawl` with `{"intent": "foo"}` → 422 (rejected by the `Literal`).

---

## Out of Scope (and Phasing)

- **LLM topic→source selection** — phase 1 uses a fixed curated list. `select_sources` is the seam for
  phase 2.
- **Prominence/clustering for significance** — phase 1 scores each article in isolation. Cross-source
  "this is hot because everyone leads with it" is phase 2.
- **A separate per-article fact-extraction stage** — deliberately removed; the scorer reads markdown and
  emits the final record. The ranked output consumes no raw `extractor`-style facts, so a separate
  extraction call would produce unused data.
- **Conversational clarification in the engine** — there is no `clarify` intent. A no-target request is a
  briefing, not a question to bounce back; the engine stays one-shot and stateless.
- **Gradio UI** — the ranked payload shape is defined here so the UI can adopt it later; wiring it into
  `gradio/` is separate work.
