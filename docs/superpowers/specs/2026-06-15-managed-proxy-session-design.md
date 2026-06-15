# Design: ManagedProxySession — Job-Scoped Proxy Session Manager

**Prepared:** 2026-06-15

**Revision history:**

- Initial draft: full design covering module structure, call chain, retry policy, CAPTCHA detection, domain delay, and tests
- Rev 2: atomic acquisition replaces get_credentials + record_request; separate transient/block retry counters; explicit no-proxy path; domain delay moved per-attempt; CAPTCHA signals narrowed; rotate accepts reason; session ID prefix terminology; doc header and code-fence language tags added

---

## Overview

Add opt-in proxy support to the crawl engine. When `PROXY_URL` is set, every fetch is routed through a username-encoded sticky session scoped to the crawl job and the target domain. When `PROXY_URL` is absent, current behaviour is preserved exactly — including the existing same-proxy 429 retry path.

Proxy credentials are never exposed to `CrawlRequest`, the Gradio package, API response payloads, or logs.

---

## Architecture

```text
execute()
  │
  ├─ ProxySettings.from_env()
  │    ├─ enabled=True  → ManagedProxySession(settings)
  │    └─ enabled=False → proxy_session = None
  │
  ├─ fetch_page(seed, ..., proxy_session=proxy_session)   ← direct path
  └─ run_agent(seed, config, state, proxy_session=proxy_session)   ← agent path
         └─ fetch_page(url, ..., proxy_session=proxy_session)
                └─ _fetch_with_retries(url, cfg, proxy_session=proxy_session)
                       ├─ per-attempt: acquire_credentials(domain) → (creds, wait)
                       ├─ sleep(wait) if wait > 0
                       ├─ cfg.clone(proxy_config=creds.to_dict())
                       ├─ arun(url, config=cfg_for_attempt)
                       └─ blocked? → rotate(domain, reason=...) → backoff → retry once
```

---

## New Module: `crawl_engine/proxy.py`

### `ProxySettings`

Reads environment variables once at construction. Immutable.

```python
PROXY_URL                    # required — proxy disabled if absent
PROXY_USERNAME_TEMPLATE      # e.g. "customer-name-session-{session_id}"
PROXY_PASSWORD
PROXY_ROTATE_AFTER_REQUESTS  # default: 20
PROXY_DOMAIN_DELAY_SECONDS   # default: 2
PROXY_BLOCK_BACKOFF_SECONDS  # default: 30
```

`enabled: bool` is `True` only when `PROXY_URL` is non-empty. All consumers check `enabled` before acting.

### `ProxyCredentials`

Frozen dataclass. Fields: `server: str`, `username: str`, `password: str`.

- `to_dict() -> dict` — returns `{"server": ..., "username": ..., "password": ...}` for `CrawlerRunConfig.proxy_config`.
- `__repr__` and `__str__` omit `password`.

### `_DomainSession` (internal)

Dataclass: `session_id: str` (UUID4 hex), `request_count: int`, `last_request_at: float` (monotonic timestamp, updated on each `acquire_credentials` call).

### `ManagedProxySession`

Job-scoped. One instance per `execute()` invocation.

State:

- `_settings: ProxySettings`
- `_sessions: dict[str, _DomainSession]` — keyed on normalised domain (`netloc` lowercased, `www.` stripped)
- `_lock: asyncio.Lock`

All public methods are `async` and acquire `_lock`. The lock is never held during `arun`, `asyncio.sleep`, or any I/O.

#### Public API

```python
async def acquire_credentials(domain: str) -> tuple[ProxyCredentials | None, float]
```

Single atomic operation. Under the lock:

1. On first visit, creates a new `_DomainSession` (UUID4 hex session ID, count 0).
2. Computes `wait = max(0.0, settings.domain_delay - (monotonic() - last_request_at))` from the *previous* `last_request_at`.
3. If `request_count >= settings.rotate_after_requests`, calls `_rotate_unlocked(domain, reason="threshold")`.
4. Increments `request_count` and sets `last_request_at = monotonic()`.
5. Returns `(ProxyCredentials | None, wait)`. Returns `(None, 0.0)` when not enabled.

Username is constructed as `settings.username_template.format(session_id=session.session_id)`.

The caller sleeps `wait` seconds outside the lock before using the credentials.

```python
async def rotate(domain: str, *, reason: str) -> None
```

Acquires the lock and calls `_rotate_unlocked(domain, reason=reason)`. Used externally by `_fetch_with_retries` on a blocking response. Does not return credentials — the next `acquire_credentials` call creates the new session.

`_rotate_unlocked(domain, reason)` generates a new UUID4 hex session ID, resets `request_count` to 0, and logs `domain`, `session_id[:8]` (prefix), `reason`, and previous `request_count`.

---

## Integration Changes

### `runner.py` — `execute()`

```python
settings = ProxySettings.from_env()
proxy_session = ManagedProxySession(settings) if settings.enabled else None
```

Both the direct-fetch path and the `run_agent` path receive this single instance. No other caller creates `ManagedProxySession`.

### Signature changes (keyword-only, default `None`)

```python
# agent.py
async def run_agent(
    seed_url: str,
    config: AgentConfig,
    state: CrawlState | None = None,
    *,
    proxy_session: ManagedProxySession | None = None,
) -> CrawlState

# crawler.py
async def fetch_page(
    url: str,
    css_selector: str | None = None,
    *,
    article_body: bool = True,
    proxy_session: ManagedProxySession | None = None,
) -> PageResult

async def _fetch_with_retries(
    url: str,
    cfg: CrawlerRunConfig,
    *,
    proxy_session: ManagedProxySession | None = None,
) -> PageResult
```

Existing callers pass nothing; the no-proxy path is the default.

### `_BROWSER_CFG` unchanged

Proxy credentials are injected per-attempt via `cfg.clone(proxy_config=creds.to_dict())`. `_BROWSER_CFG` and `_make_cfg` are not modified.

---

## Retry Policy in `_fetch_with_retries`

Two fully independent paths based on whether `proxy_session` is set.

### Managed-proxy path (`proxy_session` is not `None`)

```python
domain = normalised_domain(url)
transient_retries = 0
block_rotations = 0

while True:
    creds, wait = await proxy_session.acquire_credentials(domain)
    if wait > 0:
        await asyncio.sleep(wait)

    cfg_for_attempt = cfg.clone(proxy_config=creds.to_dict())
    try:
        result = await crawler.arun(url=url, config=cfg_for_attempt)
    except Exception as exc:
        if transient_retries < MAX_RETRIES:
            transient_retries += 1
            await asyncio.sleep(2 ** transient_retries)
            continue
        return PageResult(success=False, error=str(exc))

    if _is_blocked(result):                    # 403, 429, or CAPTCHA
        if block_rotations >= 1:
            return PageResult(success=False, error="proxy_blocked")
        reason = "captcha" if _is_captcha_response(result) else f"http_{result.status_code}"
        await proxy_session.rotate(domain, reason=reason)
        backoff = _retry_after(result) if result.status_code == 429 else settings.block_backoff
        await asyncio.sleep(backoff)
        block_rotations += 1
        continue

    if result.status_code and result.status_code >= 500:
        if transient_retries < MAX_RETRIES:
            transient_retries += 1
            await asyncio.sleep(2 ** transient_retries)
            continue
        return PageResult(success=False, error=f"HTTP {result.status_code}")

    return _build_page_result(result)
```

Block rotations and transient retries are tracked with separate counters. A blocking response always gets one rotation regardless of how many transient retries have been spent.

### No-proxy path (`proxy_session` is `None`)

Unchanged from current `_fetch_with_retries` — existing 429 retry (with Retry-After), existing 5xx exponential backoff, existing exception handling.

---

## CAPTCHA Detection

`_is_captcha_response(result: CrawlResult) -> bool` in `crawler.py`.

**Strong markers — any one is sufficient:**

- HTML contains `id="cf-challenge-running"`
- HTML contains `class="cf-browser-verification"` or `class="cf-challenge-body"`

**Phrase + status — both required together:**

- `result.status_code == 403` **and** title (lowercased) contains `"just a moment"` or `"verify you are human"`

Signals not used as standalone classifiers: `data-sitekey`, CAPTCHA script/iframe `src`, bare `"access denied"` title. These appear on normal pages with embedded widgets and would produce false positives.

A plain 403 that does not match any strong marker or the phrase+status pair is not classified as CAPTCHA. It enters the rotation branch as a plain block; the logged reason is `"http_403"` rather than `"captcha"`.

---

## Security

- `ProxyCredentials.password` is excluded from `__repr__` and `__str__`.
- Log statements include session ID prefix (`session_id[:8]`), domain, rotation reason, and request count only. No full session IDs or passwords.
- `ProxyCredentials` is not added to any Pydantic model that could be serialised into a `PageResult`, `CrawlRequest`, or API response.

---

## Environment Variables

All variables are operator-only. None appear in `CrawlRequest`, `AgentConfig`, or the Gradio package.

| Variable | Default | Description |
|---|---|---|
| `PROXY_URL` | — | Proxy server URL. Proxy disabled if absent. |
| `PROXY_USERNAME_TEMPLATE` | `"user-session-{session_id}"` | Provider username pattern. |
| `PROXY_PASSWORD` | — | Proxy password. |
| `PROXY_ROTATE_AFTER_REQUESTS` | `20` | Rotate session after this many credentials issued. |
| `PROXY_DOMAIN_DELAY_SECONDS` | `2` | Minimum seconds between requests to the same domain. |
| `PROXY_BLOCK_BACKOFF_SECONDS` | `30` | Sleep after a blocking response before the rotation retry. |

---

## Tests

### `tests/test_proxy.py` (new — unit, no network)

1. `ProxySettings.from_env()` → `enabled=False` when `PROXY_URL` absent
2. `acquire_credentials(domain)` → `(None, 0.0)` when not enabled
3. First `acquire_credentials(domain)` → creates session with UUID4 hex session ID, returns `wait=0.0`
4. Immediate second `acquire_credentials(same_domain)` → same session ID, `wait > 0`
5. `acquire_credentials(different_domain)` → separate session ID
6. `rotate(domain, reason="test")` → new session ID, different from previous
7. `acquire_credentials` × N → auto-rotates at threshold, new session ID on next call
8. Concurrent `acquire_credentials` calls → consistent state (no race), counts correct
9. `repr(ProxyCredentials(...))` → password absent

### `tests/test_crawler_fetch_page.py` (extend)

10. 403 + no proxy → existing behavior; `rotate` never called
11. 403 + proxy → `rotate` called once with `reason="http_403"`, retry attempted
12. Second block after rotation → `PageResult(success=False, error="proxy_blocked")`, no further rotation
13. 429 with `Retry-After: 5` header → sleeps ~5 s, rotates with `reason="http_429"`
14. CAPTCHA response (`id="cf-challenge-running"` in HTML) → `rotate` called with `reason="captcha"`
15. `data-sitekey` alone → `_is_captcha_response` returns `False`, enters plain-403 rotation path
16. Plain 403 without strong CAPTCHA marker → rotation triggered, `_is_captcha_response` returns `False`
17. 5xx → transient exponential backoff, `rotate` never called
18. Exception on `arun` → transient retry counter incremented, `rotate` never called
19. Block rotation does not consume transient retry budget (5xx + 403 sequence still gets both retries)
20. Domain delay: second `acquire_credentials` to same domain returns `wait > 0`; caller sleeps
21. `PageResult` contains no proxy credential fields

### `tests/test_runner.py` (extend)

22. Direct-fetch and agent paths receive the same `ManagedProxySession` instance from `execute()`

---

## Crawl4AI Fields Left Unset

```python
proxy_rotation_strategy    = None
proxy_session_id           = None
proxy_session_ttl          = None
proxy_session_auto_release = False
```

A future static proxy-pool backend could use Crawl4AI's native rotation strategy. The current managed-provider backend injects one dynamically generated `ProxyConfig` per attempt via `acquire_credentials`.
