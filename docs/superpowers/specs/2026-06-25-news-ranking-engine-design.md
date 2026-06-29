# Design: News Ranking Engine — Impact and Briefing Modes

**Prepared:** 2026-06-25

**Revision history:**

- Initial draft: unify impact and briefing into one ranking engine behind a general `--prompt`.
- Rev 2: bound rank-mode fanout (rank-specific `max_pages`, job-wide article cap, scoring concurrency limit), account scoring tokens, match article pages on `final_url`, split `filtered_count` into weak vs error counts, constrain `intent` to an enum.
- Rev 3: round-robin the job-wide article cap so it draws evenly across sources, pin rank-mode `max_depth=1`, record cross-source duplicates as an accepted phase-1 limitation.
- Rev 4: re-derive collection from RSS feeds (validated on real sources) instead of agent-loop crawling; collapse to score-then-fetch on RSS title+summary; remove the keyword-scorer, anchor-text-capture, and `slug_to_title` ideas (obsoleted by RSS); add validated scoring-calibration rules (anchor-on-title, default-0, derive direction in code) from an end-to-end spike.

---

## Overview

Today `--prompt` answers one shape of request: "go to this URL and crawl/extract." It always
requires a seed URL (`prompt_parser.py:88`, `cli.py:126`, `service.py:134`). This design generalizes
`--prompt` into the single front door and adds a second answer shape: **rank today's economy/finance
news**, returned as a justified, ranked shortlist rather than a flat page dump.

Two user-facing features share one engine:

- **Impact mode** — the user names one or more **targets** (a price, commodity, sector, company,
  indicator). Each item is scored for its impact on each target, sorted by strongest impact.
  Example: *"Which Vietnamese economy news this morning may affect gasoline retail and global crude
  oil prices?"*
- **Briefing mode** — the user names **no target**. Each item is scored for general **significance**.
  Example: *"Give me the hot economy news this morning."*

These are not two pipelines. They are **one ranking engine with a pluggable scoring step**; the only
difference is the scoring prompt, and the switch is "did the user name a target?". A no-target request
is a briefing, not a vague request to clarify — there is no `clarify` intent.

### Why RSS (validated, not assumed)

Rank mode collects from a **curated set of sources**, not an arbitrary URL. Empirical probing of real
Vietnamese outlets (Rev 4) found their **RSS feeds** are the right collection surface:

- Feeds return clean, full-diacritic headlines **plus `pubDate` plus a substantive `<description>`**
  (130–290 chars of real lede with figures, dates, entities) — verified on cafef, vneconomy,
  tuoitre, thanhnien, dantri, vietnamnet, nhandan.
- A plain `httpx` GET of a feed replaces a headless-browser render of a noisy landing page — faster,
  cheaper, dated, and stable.
- Scraping landing-page links does **not** work uniformly: vneconomy's article links carry empty
  anchor text (crawl4ai binds the thumbnail anchor), so anchor-text capture / `slug_to_title`
  fallbacks were considered and then **dropped** — RSS makes them unnecessary.

RSS is **not** a general any-site mechanism (arbitrary/SPA sites often lack feeds, and `<head>`
auto-discovery is unreliable — vneconomy/cafef have working feeds they do not advertise). It works
here precisely because the source set is curated and each feed URL is verified and stored.

---

## Architecture

`--prompt` parses into a *plan*. `runner.execute()` dispatches on `plan.intent`. The existing crawl is
one intent; the ranking engine is another.

```text
--prompt "<anything>"
        │
        ▼
parse_crawl_prompt()  →  plan = { intent, seed_url?, targets?, date_filter?, ... }
        │                         intent ∈ { "crawl", "rank" }
        ▼
runner.execute()  ── dispatch on intent ──┐
        │                                  │
   intent == "crawl"                  intent == "rank"
        │                                  │
        ▼                                  ▼
  run_agent(seed)                  select_feeds(targets)              # sources.py, curated RSS map
  → _result_payload()                     │
   [unchanged]                            ▼
                              fetch_feed(url)  (httpx, parallel)      # feeds.py
                                          │  → FeedItem(title, url, published, summary)
                                          ▼
                              keep items in the date window           # pubDate, no fetch
                                          ▼
                              score_item(item, mode, targets)         # ranker.py, 1 call / item
                              mode = "impact" if targets else "significance"
                                  (scores on title + summary)
                                          │ bounded asyncio.gather
                                          ▼
                              rank_and_filter(scored)                 # pure Python sorted()
                                          ▼
                              fetch bodies for the top survivors only # crawler.fetch_page
                                          ▼
                              _ranked_payload()
```

Scoring runs on the **RSS title + summary** (validated as sufficient), so the engine scores cheap
lightweight text first and fetches full article bodies **only for the ranked survivors** — the
"score-then-fetch" collapse. Crawl, feed-fetch, ranking, and the output envelope are mode-independent.

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
  keys in the same response, not a separate classifier pass.
- The scoring **mode is derived, not parsed** — `mode = "impact" if targets else "significance"`.
- **The seed-URL guard becomes conditional on intent.** `seed_url` is required only when
  `intent == "crawl"`. For `intent == "rank"`, a missing `seed_url` is normal. The guards at
  `prompt_parser.py:88`, `cli.py:126`, and `service.py:134` are relaxed accordingly.
- **No `keywords` field.** Keyword matching against Vietnamese URL slugs was considered and dropped:
  collection is RSS-based and scoring reads full Vietnamese text, so no keyword projection is needed.
- `date_filter` flows through the existing natural-language path (e.g. `"this morning"`), resolved by
  `engine/date_filter.py`; rank mode defaults it to today.

### Template `engine/prompts/parse_prompt.j2` (extended)

- Classify as `"crawl"` (user points at a site/URL) or `"rank"` (user asks which news *matters* —
  impact on something, or what's important today).
- For `"rank"`, extract `targets` (prices, commodities, sectors, companies, indicators). If the user
  asks for important/hot/top news with no subject, return `intent: "rank"` with `targets` omitted.
- `seed_url` is only expected for `"crawl"`.

---

## New Module: `engine/sources.py`

Holds the curated RSS map and selects which feeds a rank run reads.

### Design Decisions

- **Phase 1 is a fixed curated `{label: feed_url}` map** of verified Vietnamese economy/finance feeds.
  Seeded from the probed-working set: cafef, vneconomy, tuoitre, thanhnien, dantri, vietnamnet,
  nhandan. Each URL is stored explicitly because `<head>` auto-discovery is unreliable.
- **Topic→feed selection via LLM is explicitly phase 2.** `select_feeds` is the seam; phase 1 returns
  the whole curated list regardless of `targets`.
- For any curated source lacking a usable feed, an **HTML-parse fallback** (BeautifulSoup over the
  landing page, recovering headline anchors) lives in `feeds.py`; the map records which sources need it.

### Public Interface

```python
def select_feeds(targets: list[str]) -> list[str]
```

- Returns feed URLs to read. Phase 1 returns the curated list. Never empty.

---

## New Module: `engine/feeds.py`

Fetches and normalizes a feed into dated items — the RSS adapter (plus HTML fallback).

### Design Decisions

- **`httpx` GET, no browser** — feeds are static XML; this is the cheap path.
- Parse `title`, `link`, `pubDate`, `description` into a `FeedItem`. `pubDate` parses to a date for the
  window filter; `description` is HTML-stripped and used both as a scoring input and as fallback
  evidence.
- **HTML-parse fallback** for sources without a feed: BeautifulSoup selects article-pattern anchors
  with non-empty text (proven to recover full headlines where crawl4ai's link extractor returns
  empty anchor text). Never raises — a failed feed yields an empty list and is logged.

### Public Interface

```python
class FeedItem(BaseModel):
    title: str
    url: str
    published: date | None
    summary: str

async def fetch_feed(url: str, client: httpx.AsyncClient) -> list[FeedItem]
```

- Returns the feed's items (or `[]` on failure). Date filtering is applied by the caller via
  `published`, reusing `engine/date_filter.is_in_range`.

---

## New Module: `engine/ranker.py`

The pluggable scoring step plus pure-Python rank/filter. Scoring reads `title + summary`; there is no
separate fact-extraction stage.

### Design Decisions

- **One Claude call per item**, parallelized with a **bounded** `asyncio.gather`, mirroring
  `extractor.extract()` (render template → Haiku → `json.loads` → `jsonschema.validate`, never raises —
  returns an error record on failure).
- **Concurrency capped by a `Semaphore`** (`SCORING_CONCURRENCY`, default 8); one shared
  `AsyncAnthropic` client threads through the gather. Items are already bounded (≤ ~50/feed, then
  date-filtered), but `RANK_MAX_ITEMS` (default 60) is a hard ceiling, applied **round-robin across
  feeds** so no feed is starved by source-order truncation.
- **`score_item` returns token `usage`** so the runner can sum scoring tokens (crawl accounting covers
  only the survivor body-fetches).
- **Impact scale: signed −5..+5** per target (sign = direction, magnitude = strength); sort key
  `max_abs_impact`. **Significance scale: 0..5**; sort key the value itself.
- **`direction` is derived in code from `sign(score)`**, not trusted from the model — the spike showed
  the model can emit `score:+1, direction:"down"`. Direction is deterministic; compute it.
- **Validated calibration rules in the scoring prompt** (from the Rev 4 spike — see below).
- **Ranking and filtering are pure Python**: `sorted()` + threshold. **Filter drops sort-key magnitude
  `< 2`** (a module constant). Weak filtering and scoring errors are counted **separately**
  (`weak_filtered_count` vs `score_error_count`), with error summaries surfaced in `meta`.

### Scoring calibration (validated by the Rev 4 spike)

The spike ran the scorer against live RSS items and exposed three failures, all addressed:

- **Anchor on the primary event in the title; the summary must not flip its direction.** Fixed a case
  where "gold falls for the 4th straight week" was scored gold-*up* off a secondary clause.
- **Default to 0.** Routine corporate PR, promotions, awards, partnerships, and single-name news with
  no sector read-through score 0. (This collapsed a pervasive "+2 everything" inflation.)
- **Derive `direction` from `sign(score)` in code** (the score/direction mismatch above).
- The `< 2` filter then removes residual weak (+1) noise, so single-name PR that still scrapes a +1
  never reaches the output.

These three cases are regression tests for the scoring prompt (below).

### Public Interface

```python
async def score_item(
    item: FeedItem,
    mode: str,                      # "impact" | "significance"
    targets: list[str],
    *,
    client: anthropic.AsyncAnthropic,
    semaphore: asyncio.Semaphore,
) -> dict

def rank_and_filter(scored: list[dict]) -> tuple[list[dict], int, list[dict]]
```

- `score_item` returns a scored record (shapes below) or `{"error","url"}` on failure; never raises.
  Both shapes carry `usage` (`{"input_tokens","output_tokens"}`). `direction` is set in code.
- `rank_and_filter` returns `(ranked_kept, weak_filtered_count, error_records)` — sorted descending,
  weak items removed and counted, errors separated for `meta`.

### Scored record shapes

Impact mode:

```json
{
  "title": "...", "url": "...", "published": "2026-06-29", "max_abs_impact": 3,
  "impacts": [
    {"target": "...", "score": -3, "direction": "down", "rationale": "...", "evidence": "..."}
  ]
}
```

Significance mode:

```json
{"title": "...", "url": "...", "published": "2026-06-29", "significance": 4,
 "rationale": "...", "evidence": "..."}
```

### Templates

- `engine/prompts/score_impact.j2` — title + summary + targets → one `impacts[]` entry per target,
  with the calibration rules above.
- `engine/prompts/score_significance.j2` — title + summary → 0..5 significance, rationale, evidence,
  same calibration discipline (default-0, anchor-on-title).

---

## Runner Changes (`engine/runner.py`)

### Design Decisions

- **Dispatch on `intent` explicitly**, replacing the implicit `if not config.goal and not
  config.extract_prompt` heuristic at `runner.py:82`.
- **Collection is RSS, not the agent loop.** `_execute_rank` reads feeds in parallel (`httpx`),
  date-filters by `published`, scores `title+summary`, ranks, then fetches **only the survivor bodies**
  via the existing `fetch_page` (for a richer excerpt; the RSS summary already provides fallback
  evidence). The agent loop stays the engine for `intent == "crawl"`.
- **Token accounting sums survivor body-fetches + scoring `usage`.**
- **Live progress is coarse for rank jobs (phase 1)** — collection/scoring run outside the job
  `CrawlState`; progress reflects survivor fetches. Finer progress is phase 2.

### Sketch

```python
async def _execute_rank(request, state, proxy_rotator) -> dict:
    feeds = select_feeds(request.targets)
    lo, hi = parse_date_filter(request.date_filter or "today")
    async with httpx.AsyncClient() as hc:
        feed_items = await asyncio.gather(*[fetch_feed(u, hc) for u in feeds])
    items = roundrobin([
        [it for it in lst if is_in_range(it.published, lo, hi)] for lst in feed_items
    ])[:RANK_MAX_ITEMS]

    mode = "impact" if request.targets else "significance"
    client = anthropic.AsyncAnthropic()
    sem = asyncio.Semaphore(SCORING_CONCURRENCY)
    scored = await asyncio.gather(*[
        score_item(it, mode, request.targets, client=client, semaphore=sem) for it in items
    ])
    ranked, weak, errors = rank_and_filter(scored)
    survivors = await _fetch_bodies(ranked[:RANK_MAX_SURVIVORS], proxy_rotator)  # excerpt enrichment
    return _ranked_payload(request, mode, ranked, weak, errors, scored, survivors)
```

### Ranked payload

```json
{
  "meta": {
    "generated_at": "...", "mode": "impact", "targets": ["..."],
    "feeds_read": ["..."], "items_scored": 23, "date_window": ["...","..."],
    "weak_filtered_count": 15, "score_error_count": 3,
    "score_errors": [{"url": "...", "error": "..."}],
    "total_input_tokens": 0, "total_output_tokens": 0
  },
  "ranked_articles": [ ... ]
}
```

`targets` present only in impact mode. Token totals sum survivor body-fetch + scoring usage.

---

## CLI and HTTP Changes

`--prompt` and the HTTP `prompt` field already exist and stay as-is.

- **`engine/cli.py`** — seed-URL guard at `cli.py:126` becomes conditional on `intent == "crawl"`;
  resolve `intent`/`targets` from the parsed dict (no new flags).
- **`engine/contract.py`** — add to `CrawlRequest`:

  ```python
  intent: Literal["crawl", "rank"] = "crawl"
  targets: list[str] = Field(default_factory=list)
  ```

  `intent` is a constrained `Literal` (not bare `str`) so a body like `{"intent": "foo"}` is rejected,
  not silently routed to crawl. Update `_require_seed_url_or_prompt`: `seed_url` required for
  `intent == "crawl"` only. `to_agent_config()` unchanged.
- **`engine/service.py`** — after the existing parse+merge, make the seed-URL check at `service.py:134`
  conditional on `intent == "crawl"`.

---

## Error Handling

| Situation | Behaviour |
|---|---|
| `crawl` intent, no seed URL | unchanged — CLI logs/returns; HTTP 400/422 |
| `rank` intent, no seed URL | normal — feeds come from `select_feeds()` |
| A feed fails to fetch/parse | `fetch_feed` returns `[]`, logged; other feeds proceed |
| One item's `score_item` fails | error record separated into `score_errors`, counted; run continues |
| All items weak | empty `ranked_articles` with `weak_filtered_count` = items scored — valid result |
| A survivor body-fetch fails | RSS `summary` remains the evidence; item still ranked |

`score_item` and `fetch_feed` never raise — one bad feed or item never sinks a rank run.

---

## Tests

### `tests/engine/test_prompt_parser.py` (extend)

1. Prompt naming targets → `intent == "rank"`, `targets` populated, no `seed_url` required.
2. "hot economy news this morning" → `intent == "rank"`, `targets` empty.
3. Prompt with a URL → `intent == "crawl"`, `seed_url` present (existing behaviour).
4. `rank` intent, no `seed_url` → no `PromptParseError`.

### `tests/engine/test_feeds.py` (new)

5. RSS XML fixture → `FeedItem`s with title, url, parsed `published`, HTML-stripped `summary`.
6. Malformed/empty feed → `[]`, never raises.
7. HTML-parse fallback fixture → recovers `(title, url)` from article anchors.

### `tests/engine/test_ranker.py` (new) — mock `ranker.anthropic.AsyncAnthropic`

8. Impact, two targets → one `impacts[]` entry per target, correct `max_abs_impact`.
9. Significance → 0..5 value, rationale, evidence; no `impacts`.
10. **Calibration:** "price falls" item scores that target **down**, not up (anchor-on-title).
11. **Calibration:** routine single-name PR scores 0 (default-0).
12. **`direction` derived from `sign(score)`** — a model record with mismatched direction is corrected.
13. Malformed JSON → error record, never raises; record carries `usage`.
14. `rank_and_filter` drops magnitude `< 2`, sorts descending, separates `weak_filtered_count` from
    `error_records`.

### `tests/engine/test_runner.py` (extend) — collaborators mocked

15. `rank` dispatches `_execute_rank`: reads feeds, date-filters, scores, ranks, fetches survivor
    bodies, returns a `ranked_articles` payload.
16. Round-robin cap: items exceeding `RANK_MAX_ITEMS` across feeds → capped, every feed represented.
17. Payload `total_*_tokens` = survivor-fetch totals + summed `score_item` usage.
18. `crawl` path unchanged.

### `tests/engine/test_service.py` (extend)

19. `POST /crawl` with a `rank` prompt and no `seed_url` → job created (no 400).
20. `POST /crawl` with a `crawl` prompt and no resolvable `seed_url` → 400 (unchanged).
21. `POST /crawl` with `{"intent": "foo"}` → 422.

---

## Out of Scope (and Phasing)

- **LLM topic→feed selection** — phase 1 reads the whole curated map. `select_feeds` is the phase-2 seam.
- **General any-site collection** — RSS-first is a curated-source strategy, not an arbitrary-URL crawler.
  The `crawl` intent still serves arbitrary URLs via the agent loop.
- **Prominence/clustering and cross-source dedup** — phase 1 scores items in isolation; the same wire
  story from multiple feeds may appear multiple times. Accepted phase-1 limitation.
- **Few-shot scoring examples** — the rubric prompt is enough for phase 1 (residual +1 PR is filtered);
  few-shot calibration to push such items to 0 is a later refinement.
- **Conversational clarification in the engine** — no `clarify` intent; a no-target request is a briefing.
- **Gradio UI** — the ranked payload shape is defined here for later adoption; wiring is separate work.
