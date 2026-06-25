# Design: Active Date-Aware Crawl Discovery

**Prepared:** 2026-06-24  
**Revised:** 2026-06-25

---

## Overview

The current crawler parses natural-language date filters and drops fetched article pages whose
publish date is outside the requested range. This is correct but passive: the agent only sees
links visible on the seed page and cannot reach articles that require pagination or are absent
from the seed listing.

This design adds a three-stage candidate pipeline before the agent loop. The crawler first
discovers candidate article URLs from the site's sitemap, filters them cheaply by date and
pattern, optionally scores them by topic relevance, then pre-loads the agent frontier with
matching URLs. The agent loop is unchanged — it still fetches, reads, and extracts; post-fetch
`detect_page_date()` remains the authoritative date check.

---

## Problem

For a query like `collect finance news from the last 7 days`, the current crawler:

- Reads the seed listing page and queues only links visible there
- Has no way to navigate pagination to find older articles not on the first page
- Fetches articles speculatively and drops them after fetch if they are out of range

The agent cannot "actively search" for articles at the right date — it can only react to what
the seed page shows.

---

## Goals

- Discover candidate article URLs from the site's sitemap before any article is fetched.
- Filter candidates cheaply using sitemap dates and URL-embedded dates.
- Optionally score candidates by topic relevance using BM25 on page head content.
- Pre-load the agent frontier with date-matching, relevance-ranked candidates.
- Keep the agent loop, post-fetch validation, and extraction path unchanged.

---

## Non-Goals

- Do not use an LLM as the primary date filter.
- Do not trust URL dates or sitemap dates as final publish dates.
- Do not require site-specific integrations before the generic flow works.
- Do not bypass robots.txt or site crawl limits.
- Do not replace the agent loop.

---

## Crawl4AI API Notes

`AsyncUrlSeeder` in crawl4ai 0.8.6 parses sitemap `<loc>` URLs and yields URL strings.
`validate_sitemap_lastmod=True` only checks whether the sitemap cache is stale by comparing
the sitemap's latest `<lastmod>` — it does not expose per-article `<lastmod>` values to
callers. Per-article date access requires a custom sitemap parser.

`FreshnessScorer` only handles `YYYY/MM/DD`, `YYYY-MM-DD`, `YYYY_MM_DD`, and year-only URL
patterns. It will not decode Vietnamese news URL dates such as CafeF's `188260603` encoding.
A custom `URLScorer` wrapping `detect_url_date()` is required for the fallback path.

---

## Architecture

```text
User query + date filter
  |
  v
parse_date_filter()  →  (from_date, to_date)
  |
  v
┌─────────────────────────────────────┐
│  Stage 1: Discover candidates       │
│                                     │
│  parse_site_sitemaps(seed_url)      │
│    → recurse sitemap index          │
│    → yields SitemapCandidate(       │
│        url, lastmod, news_date)     │
│                                     │
│  fallback: BestFirstCrawlingStrategy│
│  (only when sitemap is absent or    │
│   returns < threshold candidates)   │
└──────────────┬──────────────────────┘
               |
               v
┌─────────────────────────────────────┐
│  Stage 2: Filter and rank           │
│                                     │
│  date from news_date or lastmod     │
│    → else detect_url_date(url)      │
│    → drop if outside (from, to)     │
│    → keep if date unknown           │
│                                     │
│  URL pattern filter                 │
│    → keep only article-shaped URLs  │
│                                     │
│  optional BM25 head scoring         │
│    → cap at 200 HEAD requests       │
│    → score against goal keywords    │
│    → sort descending by score       │
└──────────────┬──────────────────────┘
               |
               v
┌─────────────────────────────────────┐
│  Stage 3: Feed agent frontier       │
│                                     │
│  take top min(N, max_pages) URLs    │
│  append to state.frontier           │
│  agent loop runs unchanged          │
└──────────────┬──────────────────────┘
               |
               v
Agent loop (unchanged)
  fetch → detect_page_date() → is_in_range() → collect/extract
```

---

## Stage 1: Sitemap Discovery

### Custom Sitemap Parser

`AsyncUrlSeeder` does not expose per-article dates. Implement a lightweight parser:

```python
@dataclass
class SitemapCandidate:
    url: str
    lastmod: date | None       # from <lastmod>
    news_date: date | None     # from <news:publication_date>

async def parse_site_sitemaps(seed_url: str) -> list[SitemapCandidate]
```

Date extraction priority per URL entry:

1. `<news:publication_date>` — Google News sitemap, most authoritative
2. `<lastmod>` — standard sitemap field
3. `None` — unknown; passed through to URL-date fallback in Stage 2

### Sitemap Index Recursion

Many news sites expose a sitemap index (`/sitemap_index.xml`, `/sitemap.xml`) pointing to
daily or monthly sub-sitemaps. The parser must recurse one level into index files, fetching
each child sitemap and merging results. Recursion is limited to one level; deeper nesting is
treated as a single sitemap.

### Fallback: BestFirstCrawlingStrategy

When sitemap discovery returns fewer than a configurable threshold of candidates (default: 10),
fall back to `BestFirstCrawlingStrategy` with:

- `URLPatternFilter` keeping only article-shaped URLs
- A custom `URLScorer` wrapping `detect_url_date()` to score by recency
- `max_depth=2`, `max_pages=100`

The fallback replaces Claude's link judgment during discovery only. The agent loop still handles
fetching and extraction.

---

## Stage 2: Filter and Rank

### Date Filter

```python
def filter_by_date(
    candidates: list[SitemapCandidate],
    from_date: date,
    to_date: date,
) -> list[SitemapCandidate]:
```

Per candidate, resolve date in priority order:

1. `candidate.news_date`
2. `candidate.lastmod`
3. `detect_url_date(candidate.url)`

If a date is resolved and outside `[from_date, to_date]`: drop.  
If no date can be resolved: keep (post-fetch validation will decide).

### URL Pattern Filter

Apply `looks_like_article_url()` to drop sitemap entries that are category, tag, or index
pages. Sitemaps sometimes include non-article URLs.

### Optional BM25 Head Scoring

When a `goal` string is provided and `extract_head=True` is enabled:

- Cap at 200 HEAD requests to limit cost
- Use `SeedingConfig(extract_head=True, query=goal, score_threshold=0.3)`
- Sort remaining candidates descending by BM25 score
- Skip scoring when candidate count is already below `max_pages`

BM25 scoring is opt-in via a new `active_discovery_score_heads: bool` config field.

---

## Stage 3: Feed Agent Frontier

```python
def seed_frontier_from_candidates(
    candidates: list[SitemapCandidate],
    state: CrawlState,
    max_pages: int,
) -> None:
```

- Take top `min(len(candidates), max_pages)` URLs
- Append as `(url, depth=1)` entries to `state.frontier`
- Existing seed URL stays at depth 0; candidates enter at depth 1

The agent loop then runs normally. `detect_page_date()` on the fetched page is the final
authority on whether the article falls in range.

---

## Proposed Interfaces

### `parse_site_sitemaps`

```python
async def parse_site_sitemaps(
    seed_url: str,
    *,
    max_urls: int = 2000,
) -> list[SitemapCandidate]
```

Fetches `/sitemap.xml` and `/sitemap_index.xml` from `seed_url`'s origin. Recurses one level
into index files. Returns at most `max_urls` candidates.

### `build_discovery_candidates`

```python
async def build_discovery_candidates(
    seed_url: str,
    goal: str,
    from_date: date,
    to_date: date,
    *,
    score_heads: bool = False,
    max_candidates: int = 500,
) -> list[SitemapCandidate]
```

Runs Stage 1 → Stage 2. Returns filtered, optionally ranked candidates ready for frontier
seeding. Falls back to `BestFirstCrawlingStrategy` when sitemap yields fewer than 10 results.

### `AgentConfig` additions

```python
active_discovery: bool = False          # opt-in flag
active_discovery_score_heads: bool = False
active_discovery_max_candidates: int = 500
```

Active discovery is disabled by default so existing CLI behaviour is unchanged.

### CLI addition

```
--active-discovery          Enable sitemap-based candidate discovery before crawl
--discovery-score-heads     Enable BM25 head scoring of candidates (slower)
```

---

## Integration Points

| File | Change |
|---|---|
| `engine/discovery.py` | New module: `SitemapCandidate`, `parse_site_sitemaps`, `build_discovery_candidates` |
| `engine/config.py` | Add `active_discovery`, `active_discovery_score_heads`, `active_discovery_max_candidates` |
| `engine/runner.py` | Call `build_discovery_candidates` before `run_agent` when `active_discovery=True` |
| `engine/agent.py` | Accept pre-seeded frontier; no loop changes required |
| `engine/cli.py` | Add `--active-discovery`, `--discovery-score-heads` flags |
| `engine/contract.py` | Add `active_discovery: bool` to `CrawlRequest` |

---

## Testing Strategy

| Test | Expected |
|---|---|
| Sitemap with `<news:publication_date>` | Date extracted correctly |
| Sitemap with `<lastmod>` only | Date extracted correctly |
| Sitemap index with child sitemaps | All child URLs merged |
| URL with embedded date outside range | Candidate dropped before fetch |
| URL with embedded date inside range | Candidate kept |
| URL with no date signal | Candidate kept; post-fetch decides |
| Fetched page metadata outside range | Page dropped (existing behaviour) |
| Sitemap returns 0 URLs | Fallback to BestFirstCrawlingStrategy |
| `active_discovery=False` | Existing agent loop unchanged |

Unit tests mock HTTP responses for sitemap XML. Live site checks remain integration tests.

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Sitemap absent or empty | Fall back to BestFirstCrawlingStrategy |
| Sitemap lags behind live site | URL-date fallback catches articles not yet in sitemap |
| Sitemap lastmod differs from publish date | `detect_page_date()` post-fetch is authoritative |
| Too many candidates for wide date ranges | Cap at `active_discovery_max_candidates` (default 500) |
| BM25 head scoring slow on large candidate sets | Hard cap of 200 HEAD requests; opt-in only |
| BestFirstCrawlingStrategy misses articles | It is a fallback; not expected to be complete |
| Vietnamese URL date format not decoded by FreshnessScorer | Custom scorer uses `detect_url_date()` |
