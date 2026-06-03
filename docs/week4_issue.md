Current `output.json` shows the main agent problem clearly:

**Problem**
The agent stopped before satisfying the goal.

Goal:

```text
fetch and read the full content of at least 3 economy news articles — follow links to individual article pages
```

Actual output:

```text
total_pages: 2
pages_collected: 2
urls_visited: 2
```

But those 2 pages are:

1. `https://cafef.vn` homepage
2. One article page: `gia-vang-sjc-vang-nhan-hom-nay-3-6...`

So the agent only read **1 actual article**, not at least 3.

The bad part is the `finish_reason`:

```text
... has 4 URLs remaining in the frontier at depth 1 that will be processed ...
```

That is logically wrong. Once the agent calls `finish`, this loop stops:

```python
while state.frontier and not state.finished:
```

So those 4 frontier URLs will **not** be processed.

**Root Cause**
Claude is allowed to call `finish` even when:
- the explicit goal is not satisfied
- `state.frontier` still has queued URLs
- `max_pages` has not been reached
- only 1 article page has been fetched

The code trusts the agent’s `finish` call too much.

**Secondary Issues**
- `pages_collected` counts the homepage as a page, but the goal asks for article pages. This makes progress look better than it is.
- The agent misunderstands depth. At depth `1`, it cannot enqueue depth `2` links, but it can still process other depth `1` URLs already in the frontier.
- The output does not record frontier state, so you cannot see which URLs were queued but skipped after `finish`.
- Homepage markdown is noisy, which can weaken link selection.

**Fix Direction**
Do not allow `finish` unless hard completion checks pass. For this goal, track article pages separately and reject premature finish:

```text
If goal asks for at least 3 articles:
- require at least 3 fetched article pages
- ignore or reject finish while frontier has eligible article URLs
```

At minimum, `_execute_tool("finish")` should return something like:

```text
finish rejected: goal requires 3 article pages, only 1 collected, 4 queued
```

and keep the crawl running.
