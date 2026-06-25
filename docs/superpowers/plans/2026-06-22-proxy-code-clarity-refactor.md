# Proxy Code Clarity Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the block-classification and failure-construction code in `src/crawl_tool/engine/crawler.py` easier to read, with zero *runtime* behavior change — `_fetch_managed_proxy`'s observable retry/rotation/logging behavior must be identical, even though test names and internal helper names change.

**Architecture:** Two independent, separately-committable refactors, scoped down from an earlier 3-task draft after a clarity review (see "Decisions from clarity review" below):
1. Replace `_is_blocked` + `_block_reason` (two functions, each calling Crawl4AI's native `antibot_detector.is_blocked` separately) with one `_classify_block(result) -> _BlockResult`. No wrappers kept — `_classify_block` becomes the only name, and the call site and all of its tests are rewritten to use it directly.
2. Extract the four near-identical `PageResult(success=False, ...)` constructions inside `_fetch_managed_proxy` into one `_failure_result(...)` helper.

**Decisions from clarity review:** The original draft had a third task (extracting `_PoolBackend`/`_TemplatedBackend` classes out of `ManagedProxySession` in `proxy.py`) and kept `_is_blocked`/`_block_reason` as wrappers around `_classify_block` to avoid touching their tests. Both were dropped after review:
- The backend-class split traded visible inline branching for indirection across two new classes, for only two small (~10-line) backends — judged *not* a clear readability win for this codebase, so `proxy.py` is untouched by this plan.
- Keeping `_is_blocked`/`_block_reason` as thin wrappers would have added a new dataclass and three functions where two existed, just to dedupe one inexpensive native call — the actual clarity win only shows up if `_classify_block` is the *one* name a reader has to learn, so the wrappers are removed and the tests are rewritten instead of preserved.

**Tech Stack:** Python 3.11+, `crawl4ai` (`antibot_detector.is_blocked`), `pytest` + `pytest-asyncio`, `structlog`.

## Global Constraints

- No change to `_fetch_managed_proxy`'s observable retry/rotation/logging behavior or to `ProxySettings`/`ProxyCredentials`/`PageResult` public fields. Test *names* and internal helper names may change; runtime behavior may not.
- Run `uv run python -m pytest tests/ -q -m "not integration"` after every task — see each task's expected pass count.
- Run `uv run ruff check .` and `uv run ruff format --check src/ tests/` after every task.
- Commit message format: `type: summary`, subject line only, no body, no Co-Authored-By (per `CLAUDE.md`).
- Do not touch `_fetch_with_retries` (the no-proxy path) — it is out of scope; this plan only touches the proxy-enabled path.
- Do not touch `src/crawl_tool/engine/proxy.py` — out of scope per the clarity-review decision above.
- Starting baseline: `333 passed` on `uv run python -m pytest tests/ -q -m "not integration"`.

---

### Task 1: Collapse `_is_blocked`/`_block_reason` into one `_classify_block`, and migrate all callers/tests to it directly

**Files:**
- Modify: `src/crawl_tool/engine/crawler.py:1-18` (imports), `:290-335` (the block-classification functions), `:419,432` (the call site inside `_fetch_managed_proxy`)
- Modify: `tests/engine/test_crawler_fetch_page.py` (the `_is_blocked`/`_block_reason` test block, lines ~467-583)

**Interfaces:**
- Consumes: `_antibot_is_blocked` (`crawl4ai.antibot_detector.is_blocked`, already imported at `crawler.py:15`), `_VENDOR_BLOCK_KEYWORDS` (existing, `crawler.py:292-304`, unchanged), `_blocked_result` (existing test helper, `tests/engine/test_crawler_fetch_page.py:472`, unchanged).
- Produces: `_BlockResult` (frozen dataclass: `blocked: bool`, `reason: str`) and `_classify_block(result) -> _BlockResult`. `_is_blocked` and `_block_reason` are deleted — there is no wrapper. Task 2 of this plan will call `_classify_block` directly at the `_fetch_managed_proxy` call site.

- [ ] **Step 1: Write the failing tests for `_classify_block`, replacing the old `_is_blocked`/`_block_reason` test block**

In `tests/engine/test_crawler_fetch_page.py`, find the section comment `# _is_blocked / _block_reason — backed by Crawl4AI's native antibot_detector` (just above the `_blocked_result` helper at line 472) and the 11 test functions that follow it (`test_is_blocked_403` through `test_block_reason_not_blocked_is_empty`, ending at line 583). Leave the `_blocked_result` helper itself (lines 472-483) untouched. Replace only the 11 test functions (lines ~485-583, everything after `_blocked_result` and before the next section) with:

```python
def test_classify_block_403() -> None:
    from crawl_tool.engine.crawler import _classify_block

    block = _classify_block(_blocked_result(403))
    assert block.blocked is True
    assert block.reason == "http_403"


def test_classify_block_429() -> None:
    from crawl_tool.engine.crawler import _classify_block

    block = _classify_block(_blocked_result(429))
    assert block.blocked is True
    assert block.reason == "http_429"


def test_classify_block_vendor_challenge_page() -> None:
    from crawl_tool.engine.crawler import _classify_block

    result = _blocked_result(
        status_code=403, html="<html><body><h1>Pardon Our Interruption</h1></body></html>"
    )
    block = _classify_block(result)
    assert block.blocked is True
    assert block.reason == "captcha"


def test_classify_block_data_sitekey_alone_is_not_captcha() -> None:
    """A bare data-sitekey attribute is not a vendor signature on its own —
    must not be miscategorised as captcha."""
    from crawl_tool.engine.crawler import _classify_block

    result = _blocked_result(html='<form data-sitekey="abc123"><button>Submit</button></form>')
    block = _classify_block(result)
    assert block.blocked is True
    assert block.reason == "http_403"


def test_classify_block_not_blocked_normal_article_with_recaptcha_widget() -> None:
    """A generic data-sitekey/recaptcha widget on a real, content-bearing page
    is not a vendor block signature — Crawl4AI's detector should not flag it."""
    from crawl_tool.engine.crawler import _classify_block

    html = (
        "<html><body><article>"
        "<p>" + ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 5) + "</p>"
        '<div data-sitekey="key"><script src="https://recaptcha.net/api.js"></script></div>'
        "</article></body></html>"
    )
    result = _blocked_result(status_code=200, html=html)
    block = _classify_block(result)
    assert block.blocked is False
    assert block.reason == ""


def test_classify_block_not_blocked_empty_200_response() -> None:
    """An empty body on a 200 is NOT treated as blocked by itself — generic
    near-empty/structural heuristics are deliberately not consulted outside
    403/429, since they're calibrated for raw full-page HTML and would flag
    ordinary short responses; only a named vendor/challenge signature counts."""
    from crawl_tool.engine.crawler import _classify_block

    result = MagicMock()
    result.status_code = 200
    result.html = ""
    result.metadata = {}
    result.error_message = None
    block = _classify_block(result)
    assert block.blocked is False
    assert block.reason == ""


def test_classify_block_not_blocked_500() -> None:
    """5xx is handled as a transient error with same-proxy retry, never as a
    rotation-worthy block — excluded regardless of what the detector would say."""
    from crawl_tool.engine.crawler import _classify_block

    block = _classify_block(_blocked_result(500))
    assert block.blocked is False
    assert block.reason == ""


def test_classify_block_calls_native_detector_exactly_once() -> None:
    """The bug this fixes: _is_blocked and _block_reason used to call the
    native detector separately. _classify_block must call it exactly once."""
    from unittest.mock import patch

    from crawl_tool.engine.crawler import _classify_block

    result = _blocked_result(403)
    with patch(
        "crawl_tool.engine.crawler._antibot_is_blocked",
        return_value=(True, "HTTP 403 with near-empty response (0 bytes)"),
    ) as mock_native:
        block = _classify_block(result)
    assert mock_native.call_count == 1
    assert block.blocked is True
    assert block.reason == "http_403"
```

`MagicMock` is already imported at the top of this test file (used elsewhere in the same test block) — no new import needed.

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run python -m pytest tests/engine/test_crawler_fetch_page.py -k classify_block -v`

Expected: all 8 `FAIL` with `ImportError: cannot import name '_classify_block'`.

- [ ] **Step 3: Implement `_BlockResult` and `_classify_block`; delete `_is_blocked` and `_block_reason`**

In `src/crawl_tool/engine/crawler.py`, add the `dataclass` import. `crawler.py` does not currently import it (confirmed: no `from dataclasses import ...` line exists). Change:

```python
from datetime import UTC, datetime
```
to:
```python
from dataclasses import dataclass
from datetime import UTC, datetime
```

Then replace the entire `_is_blocked` and `_block_reason` functions (current lines 307-335, everything between the `_VENDOR_BLOCK_KEYWORDS` tuple and `_build_success_result`) with:

```python
@dataclass(frozen=True)
class _BlockResult:
    blocked: bool
    reason: str  # "" when not blocked


def _classify_block(result) -> _BlockResult:
    """Classify a response using Crawl4AI's antibot_detector — exactly one
    native call per response, regardless of how many callers need the result.

    HTTP 403/429 always blocks. 5xx never blocks — handled as a transient
    error with same-proxy retry, never as a rotation-worthy block. Any other
    status only blocks if the native detector's reason text matches a named
    anti-bot vendor/challenge signature; generic near-empty-body and
    structural-integrity heuristics are deliberately not consulted outside
    403/429 — they're calibrated for raw full-page HTML and would flag
    ordinary short or stubbed 200 responses, and this codebase already
    handles unusably short scoped content via a separate full-page retry.
    """
    status = result.status_code or 0
    if status >= 500:
        return _BlockResult(False, "")

    _, native_reason = _antibot_is_blocked(status, result.html or "", result.error_message)
    is_vendor_match = any(keyword in native_reason.lower() for keyword in _VENDOR_BLOCK_KEYWORDS)

    if status in (403, 429):
        return _BlockResult(True, "captcha" if is_vendor_match else f"http_{status}")
    if is_vendor_match:
        return _BlockResult(True, "captcha")
    return _BlockResult(False, "")
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `uv run python -m pytest tests/engine/test_crawler_fetch_page.py -k classify_block -v`

Expected: all 8 `PASS`.

- [ ] **Step 5: Update the call site in `_fetch_managed_proxy`**

In `src/crawl_tool/engine/crawler.py`, in `_fetch_managed_proxy`, replace:

```python
        if _is_blocked(result):
            if block_rotations >= 1:
                logger.warning("proxy blocked after rotation", url=url, status=status)
                return PageResult(
                    url=url,
                    final_url=url,
                    status_code=status,
                    title=None,
                    markdown="",
                    fetch_time=fetch_time,
                    success=False,
                    error="proxy_blocked",
                )
            reason = _block_reason(result)
            logger.warning("fetch blocked, rotating", url=url, status=status, reason=reason)
            await proxy_session.rotate(domain, reason=reason)
```

with:

```python
        block = _classify_block(result)
        if block.blocked:
            if block_rotations >= 1:
                logger.warning("proxy blocked after rotation", url=url, status=status)
                return PageResult(
                    url=url,
                    final_url=url,
                    status_code=status,
                    title=None,
                    markdown="",
                    fetch_time=fetch_time,
                    success=False,
                    error="proxy_blocked",
                )
            logger.warning(
                "fetch blocked, rotating", url=url, status=status, reason=block.reason
            )
            await proxy_session.rotate(domain, reason=block.reason)
```

(The `PageResult(...)` block here is untouched by this task — Task 2 removes the duplication across all four sites at once.)

- [ ] **Step 6: Run the full test suite and lint**

Run: `uv run python -m pytest tests/ -q -m "not integration"`
Expected: `330 passed` (333 baseline − 11 replaced + 8 new), `13 deselected`.

Run: `uv run ruff check . && uv run ruff format --check src/crawl_tool/engine/crawler.py tests/engine/test_crawler_fetch_page.py`
Expected: `All checks passed!` (run `uv run ruff format` on both files first if formatting fails).

- [ ] **Step 7: Commit**

```bash
git add src/crawl_tool/engine/crawler.py tests/engine/test_crawler_fetch_page.py
git commit -m "refactor: collapse block classification into one native detector call"
```

---

### Task 2: Extract `_failure_result` to deduplicate the four failure-path `PageResult` constructions

**Files:**
- Modify: `src/crawl_tool/engine/crawler.py:378-475` (`_fetch_managed_proxy`)
- Test: `tests/engine/test_crawler_fetch_page.py`

**Interfaces:**
- Consumes: `PageResult` (existing, `crawl_tool.engine.models`).
- Produces: `_failure_result(url: str, status: int | None, fetch_time: float, error: str) -> PageResult`. Used only inside `_fetch_managed_proxy` in this plan; `_fetch_with_retries` (the no-proxy path) is out of scope per Global Constraints.

- [ ] **Step 1: Write the failing test for `_failure_result`**

Add to `tests/engine/test_crawler_fetch_page.py`, directly after the `_classify_block` tests added in Task 1:

```python
def test_failure_result_builds_consistent_page_result() -> None:
    from crawl_tool.engine.crawler import _failure_result

    result = _failure_result("https://example.com", 403, 1.23, "proxy_blocked")
    assert result.url == "https://example.com"
    assert result.final_url == "https://example.com"
    assert result.status_code == 403
    assert result.title is None
    assert result.markdown == ""
    assert result.fetch_time == 1.23
    assert result.success is False
    assert result.error == "proxy_blocked"


def test_failure_result_allows_none_status() -> None:
    from crawl_tool.engine.crawler import _failure_result

    result = _failure_result("https://example.com", None, 0.5, "connection reset")
    assert result.status_code is None
    assert result.error == "connection reset"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run python -m pytest tests/engine/test_crawler_fetch_page.py::test_failure_result_builds_consistent_page_result tests/engine/test_crawler_fetch_page.py::test_failure_result_allows_none_status -v`

Expected: both `FAIL` with `ImportError: cannot import name '_failure_result'`.

- [ ] **Step 3: Implement `_failure_result`**

In `src/crawl_tool/engine/crawler.py`, insert directly after `_build_success_result` (before `async def _fetch_managed_proxy`):

```python
def _failure_result(url: str, status: int | None, fetch_time: float, error: str) -> PageResult:
    """Build a failed PageResult. Shared by every failure path in
    _fetch_managed_proxy — exception, exhausted transient retries, and the
    second consecutive block."""
    return PageResult(
        url=url,
        final_url=url,
        status_code=status,
        title=None,
        markdown="",
        fetch_time=fetch_time,
        success=False,
        error=error,
    )
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `uv run python -m pytest tests/engine/test_crawler_fetch_page.py::test_failure_result_builds_consistent_page_result tests/engine/test_crawler_fetch_page.py::test_failure_result_allows_none_status -v`

Expected: both `PASS`.

- [ ] **Step 5: Replace all four duplicated `PageResult(success=False, ...)` constructions in `_fetch_managed_proxy` with `_failure_result(...)`**

In `src/crawl_tool/engine/crawler.py`, inside `_fetch_managed_proxy`:

Replace (the exception-exhausted branch):
```python
            logger.warning("fetch exception", url=url, exc=str(exc))
            return PageResult(
                url=url,
                final_url=url,
                status_code=None,
                title=None,
                markdown="",
                fetch_time=fetch_time,
                success=False,
                error=str(exc),
            )
```
with:
```python
            logger.warning("fetch exception", url=url, exc=str(exc))
            return _failure_result(url, None, fetch_time, str(exc))
```

Replace (the blocked-twice branch, already updated in Task 1 to use `block.blocked`/`status`):
```python
            if block_rotations >= 1:
                logger.warning("proxy blocked after rotation", url=url, status=status)
                return PageResult(
                    url=url,
                    final_url=url,
                    status_code=status,
                    title=None,
                    markdown="",
                    fetch_time=fetch_time,
                    success=False,
                    error="proxy_blocked",
                )
```
with:
```python
            if block_rotations >= 1:
                logger.warning("proxy blocked after rotation", url=url, status=status)
                return _failure_result(url, status, fetch_time, "proxy_blocked")
```

Replace (the 5xx-exhausted branch):
```python
            logger.warning("fetch failed", url=url, status=status)
            return PageResult(
                url=url,
                final_url=url,
                status_code=status,
                title=None,
                markdown="",
                fetch_time=fetch_time,
                success=False,
                error=f"HTTP {status}",
            )
```
with:
```python
            logger.warning("fetch failed", url=url, status=status)
            return _failure_result(url, status, fetch_time, f"HTTP {status}")
```

Replace (the generic `not result.success` branch):
```python
        if not result.success:
            error = result.error_message or f"HTTP {status}"
            logger.warning("fetch failed", url=url, status=status, error=error)
            return PageResult(
                url=url,
                final_url=url,
                status_code=status,
                title=None,
                markdown="",
                fetch_time=fetch_time,
                success=False,
                error=error,
            )
```
with:
```python
        if not result.success:
            error = result.error_message or f"HTTP {status}"
            logger.warning("fetch failed", url=url, status=status, error=error)
            return _failure_result(url, status, fetch_time, error)
```

- [ ] **Step 6: Run the full test suite and lint**

Run: `uv run python -m pytest tests/ -q -m "not integration"`
Expected: `332 passed` (330 from Task 1 + 2 new), `13 deselected`.

Run: `uv run ruff check . && uv run ruff format --check src/crawl_tool/engine/crawler.py tests/engine/test_crawler_fetch_page.py`
Expected: `All checks passed!` (run `uv run ruff format` on both files first if formatting fails).

- [ ] **Step 7: Commit**

```bash
git add src/crawl_tool/engine/crawler.py tests/engine/test_crawler_fetch_page.py
git commit -m "refactor: deduplicate failure PageResult construction in proxy fetch path"
```

---

## Explicitly Out of Scope

- **`src/crawl_tool/engine/proxy.py`** (the `_PoolBackend`/`_TemplatedBackend` split) — dropped after clarity review; see "Decisions from clarity review" above.
- **`_fetch_with_retries`** (the no-proxy path) — untouched, no duplication or branching issue exists there worth fixing in this plan.
- Any change to rotation cadence, backoff timing, or `ProxySettings`/`ProxyCredentials`/`PageResult` public fields — this plan is pure internal restructuring of `crawler.py`.
