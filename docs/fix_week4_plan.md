# Plan: Fix Premature Finish Bug (Week 4)

## Context
The agent calls the `finish` tool before satisfying the user's goal. When the goal requires "at least 3 article pages", the agent finished after only 1 article while 4 URLs remained in the frontier. The code unconditionally trusts any `finish` call — setting `state.finished = True` and halting the crawl loop immediately.

## Changes

### 1. Parse goal for minimum article count — `src/agent.py`
Add a module-level helper after imports:
```python
def _parse_min_articles(goal: str) -> int:
    m = re.search(r"at least\s+(\d+)\s+article", goal, re.IGNORECASE)
    return int(m.group(1)) if m else 0
```

### 2. Extend `CrawlState` — `src/agent.py`
Add two fields to `CrawlState`:
```python
article_pages: list[str] = Field(default_factory=list)      # URLs classified as articles
frontier_at_finish: list[str] = Field(default_factory=list) # unvisited URLs when crawl stopped
```

### 3. Article page classifier — `src/agent.py`
Add private helper alongside `_canonical`, `_same_domain`, `_allowed`:
```python
def _is_article_page(page: PageResult) -> bool:
    path_parts = [p for p in urlparse(page.final_url).path.split("/") if p]
    if len(path_parts) >= 2:
        return True
    return len(page.markdown.split()) > 200
```

### 4. Classify pages in crawl loop — `src/agent.py`
After `state.pages.append(page)` in `run_agent`:
```python
if _is_article_page(page):
    state.article_pages.append(page.final_url)
```

### 5. Guard `finish` in `_execute_tool` — `src/agent.py`
Add `min_articles: int = 0` parameter. Replace unconditional finish handler:
```python
case "finish":
    if min_articles > 0 and len(state.article_pages) < min_articles:
        queued = len(state.frontier)
        collected = len(state.article_pages)
        return (
            f"finish rejected: goal requires {min_articles} article pages, "
            f"only {collected} collected, {queued} queued"
        )
    state.finished = True
    state.finish_reason = inputs.get("reason", "")
    state.frontier_at_finish = [u for u, _ in state.frontier]
    logger.info("agent finished: %s", state.finish_reason)
    return "crawl terminated"
```
When rejected, the string is returned as a `tool_result` to Claude — `state.finished` is NOT set, so the crawl continues.

### 6. Thread `min_articles` through call chain — `src/agent.py`
- `_agent_turn(... min_articles: int = 0)` → forward to `_execute_tool`
- `run_agent`: call `_parse_min_articles(config.goal)` once at startup, pass to `_agent_turn`

### 7. Show article progress in agent prompt — `prompts/user_turn.j2`
Add to the Crawl State section:
```
- Article pages collected: {{ article_pages_count }}
```
Pass `article_pages_count=len(state.article_pages)` in the render call inside `_agent_turn`.

### 8. Emit new fields in final output — `src/output.py` / `main.py`
Add to `run_meta` dict:
```python
"article_pages_collected": len(state.article_pages),
"frontier_at_finish": state.frontier_at_finish,
```

## Files Modified
- `src/agent.py` — all core logic changes
- `prompts/user_turn.j2` — add article count to agent context
- `main.py` or wherever `run_meta` is assembled — add new output fields

## Verification
1. Run the crawler with goal `"fetch and read the full content of at least 3 economy news articles"` against `https://cafef.vn`
2. Confirm `finish` is rejected with the descriptive message when < 3 article pages collected
3. Confirm crawl continues and collects ≥ 3 articles before terminating
4. Check `output.json` shows `article_pages_collected >= 3` and `frontier_at_finish` is populated
