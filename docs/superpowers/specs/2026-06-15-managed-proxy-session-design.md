# Design: ManagedProxySession — Job-Scoped Proxy Session Manager

**Prepared:** 2026-06-15

**Revision history:**

- Initial draft: full design covering module structure, call chain, retry policy, CAPTCHA detection, domain delay, and tests
- Rev 2: atomic acquisition replaces get_credentials + record_request; separate transient/block retry counters; explicit no-proxy path; domain delay moved per-attempt; CAPTCHA signals narrowed; rotate accepts reason; session ID prefix terminology; doc header and code-fence language tags added
- Rev 3 (2026-06-19): static proxy-pool backend added (`PROXY_LIST_FILE` / `WEBSHARE_PROXY_LIST_FILE`); `_DomainSession` gains `proxy_index`; `rotate` advances through the pool round-robin when a pool is configured; `PROXY_USERNAME_TEMPLATE` validated to require `{session_id}` when no pool is configured; test env isolation moved to an autouse fixture in `tests/conftest.py`
- Rev 4 (2026-06-22): pool rotation migrated to Crawl4AI's native `RoundRobinProxyStrategy` — `_DomainSession.proxy_index` removed, `proxy_index` advancement replaced by `get_proxy_for_session(domain)` / `release_session(domain)`; CAPTCHA/block detection migrated to Crawl4AI's native `antibot_detector.is_blocked`, replacing the hardcoded 3-marker `_is_captcha_response`; `_is_blocked` and a new `_block_reason` keep the exact same boundary (403/429 always blocked, 5xx never blocked) but classify "captcha" vs plain status via native's much broader vendor-pattern library

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
PROXY_URL                    # single managed-provider proxy — disabled if absent and no pool
PROXY_USERNAME_TEMPLATE      # e.g. "customer-name-session-{session_id}"; required when PROXY_URL is set and no pool is configured
PROXY_PASSWORD
PROXY_ROTATE_AFTER_REQUESTS  # default: 20
PROXY_DOMAIN_DELAY_SECONDS   # default: 2
PROXY_BLOCK_BACKOFF_SECONDS  # default: 30
PROXY_LIST_FILE              # path to a static proxy-pool file
WEBSHARE_PROXY_LIST_FILE     # alias for PROXY_LIST_FILE
```

`enabled: bool` is `True` when `PROXY_URL` is non-empty **or** a proxy pool is loaded. All consumers check `enabled` before acting.

Two mutually exclusive backends, selected at `from_env()`:

- **Managed-provider backend** — `PROXY_URL` set, no pool file. Credentials are generated per session by formatting `PROXY_USERNAME_TEMPLATE` with a UUID4 `session_id`, so the provider rotates the exit IP server-side. `from_env()` raises `ValueError` if `PROXY_URL` is set, no pool is configured, and `PROXY_USERNAME_TEMPLATE` does not contain `{session_id}` — a static username can never rotate under this backend.
- **Static pool backend** — `PROXY_LIST_FILE` (or `WEBSHARE_PROXY_LIST_FILE`) set. `_load_proxy_pool()` reads the file once at construction into `proxy_pool: tuple[ProxyCredentials, ...]`. Rotation cycles through the pool round-robin instead of re-templating a username; the pool takes precedence over `PROXY_URL` when both are set.

### `_load_proxy_pool()` / `_proxy_credentials_from_line()`

`_load_proxy_pool() -> tuple[ProxyCredentials, ...]` reads `PROXY_LIST_FILE` or `WEBSHARE_PROXY_LIST_FILE`, returns `()` if neither is set, otherwise parses every non-blank line.

`_proxy_credentials_from_line(line: str) -> ProxyCredentials` accepts three line formats:

- `scheme://user:pass@host:port` or `user:pass@host:port` (defaults to `http://`)
- `host:port:username:password` (4 colon-separated fields)
- `host:port` (2 fields, no credentials)

Any other field count raises `ValueError("unsupported proxy list line format")`.

### `ProxyCredentials`

Frozen dataclass. Fields: `server: str`, `username: str`, `password: str`.

- `to_dict() -> dict` — returns `{"server": ..., "username": ..., "password": ...}` for `CrawlerRunConfig.proxy_config`.
- `__repr__` and `__str__` omit `password`.

### `_DomainSession` (internal)

Dataclass: `session_id: str` (UUID4 hex), `request_count: int`, `last_request_at: float` (monotonic timestamp, updated on each `acquire_credentials` call).

Pool position is no longer tracked here (Rev 4) — `ManagedProxySession` holds a `crawl4ai.RoundRobinProxyStrategy` instance when `settings.proxy_pool` is set, and asks it for the domain's current pool entry via `get_proxy_for_session(domain)`.

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
5. If a pool strategy is configured, returns `(creds, wait)` where `creds` wraps the `crawl4ai.ProxyConfig` from `pool_strategy.get_proxy_for_session(domain)` (no TTL — sticky until explicitly rotated) back into our own `ProxyCredentials` so password redaction stays intact.
6. Otherwise returns `(ProxyCredentials | None, wait)` built from `settings.username_template.format(session_id=session.session_id)`. Returns `(None, 0.0)` when not enabled.

The caller sleeps `wait` seconds outside the lock before using the credentials.

```python
async def rotate(domain: str, *, reason: str) -> None
```

Acquires the lock and calls `_rotate_unlocked(domain, reason=reason)`. Used externally by `_fetch_with_retries` on a blocking response. Does not return credentials — the next `acquire_credentials` call creates the new session.

`_rotate_unlocked(domain, reason)` generates a new UUID4 hex session ID, resets `request_count` to 0, and logs `domain`, `session_id[:8]` (prefix), `reason`, and previous `request_count`. When a pool strategy is configured, it also awaits `pool_strategy.release_session(domain)` first, so the next `get_proxy_for_session(domain)` call advances to the next pool entry round-robin; the managed-provider backend instead relies on the new session ID alone to get a new exit IP from the provider.

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

## Block / CAPTCHA Detection (Rev 4 — migrated to Crawl4AI native)

`_is_blocked(result) -> bool` and `_block_reason(result) -> str` in `crawler.py`, both backed by `crawl4ai.antibot_detector.is_blocked(status_code, html, error_message)` instead of the original 3-marker hardcoded heuristic.

**Boundary (unchanged from Rev 1–3):**

- `status_code in (403, 429)` → always blocked.
- `status_code >= 500` → never blocked (handled as transient, same-proxy retry).
- Any other status → blocked only if the native detector's reason text matches a named vendor/challenge keyword (`_VENDOR_BLOCK_KEYWORDS`: cloudflare, akamai, perimeterx, datadome, imperva, incapsula, sucuri, kasada, captcha, challenge, network security). Generic near-empty-body and structural-integrity heuristics are deliberately **not** consulted outside 403/429 — they're calibrated for raw full-page HTML and would flag ordinary short 200 responses; this codebase already retries via a separate full-page fallback when scoped markdown is too short (see `fetch_page`).

**Reason tagging (`_block_reason`):** `"captcha"` when the native reason matches a vendor keyword, else `f"http_{status}"`. Both 403 and 429 still pass through native detection to decide the tag — e.g. a 403 with a matched Cloudflare/Akamai/etc. pattern tags `"captcha"`; a plain 403 with no pattern match tags `"http_403"`.

Native's pattern library covers far more than the original 3 Cloudflare markers — Cloudflare (challenge-form token, error-code span, JS orchestrate path), Akamai (`Reference #`, "Pardon Our Interruption"), PerimeterX, DataDome, Imperva/Incapsula, Sucuri, and Kasada, plus a 3-tier severity model (structural markers → generic short-page terms → structural-integrity fallback) — see `crawl4ai/antibot_detector.py` for the full pattern set.

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
| `PROXY_URL` | — | Managed-provider proxy server URL. Ignored when a pool is configured. |
| `PROXY_USERNAME_TEMPLATE` | `"user-session-{session_id}"` | Provider username pattern. Must contain `{session_id}` when `PROXY_URL` is set and no pool is configured. |
| `PROXY_PASSWORD` | — | Managed-provider proxy password. |
| `PROXY_ROTATE_AFTER_REQUESTS` | `20` | Rotate session after this many credentials issued. |
| `PROXY_DOMAIN_DELAY_SECONDS` | `2` | Minimum seconds between requests to the same domain. |
| `PROXY_BLOCK_BACKOFF_SECONDS` | `30` | Sleep after a blocking response before the rotation retry. |
| `PROXY_LIST_FILE` | — | Path to a static proxy-pool file (`host:port:user:pass` lines). Takes precedence over `PROXY_URL`. |
| `WEBSHARE_PROXY_LIST_FILE` | — | Alias for `PROXY_LIST_FILE`. |

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
14. Vendor challenge page (e.g. "Pardon Our Interruption") → `rotate` called with `reason="captcha"`
15. `data-sitekey` alone → `_block_reason` returns `"http_403"`, not `"captcha"` (no vendor pattern match)
16. Plain 403 without a vendor signature → rotation triggered, `_block_reason` returns `"http_403"`
17. 5xx → transient exponential backoff, `rotate` never called
18. Exception on `arun` → transient retry counter incremented, `rotate` never called
19. Block rotation does not consume transient retry budget (5xx + 403 sequence still gets both retries)
20. Domain delay: second `acquire_credentials` to same domain returns `wait > 0`; caller sleeps
21. `PageResult` contains no proxy credential fields

### `tests/test_runner.py` (extend)

22. Direct-fetch and agent paths receive the same `ManagedProxySession` instance from `execute()`

### `tests/test_proxy.py` — pool backend (extend)

23. `ProxySettings.from_env()` with `PROXY_URL` set, no pool, and a static `PROXY_USERNAME_TEMPLATE` → raises `ValueError`
24. `ProxySettings.from_env()` with `PROXY_LIST_FILE` pointing at a `host:port:user:pass` file → `enabled=True`, `proxy_pool` populated, entries parsed correctly
25. `rotate(domain, reason=...)` with a pool configured → the next `acquire_credentials` returns the next pool entry's `server`, wrapping back to the first entry after the pool is exhausted (`RoundRobinProxyStrategy` round-trip)

### `tests/test_crawler_fetch_page.py` — pool backend (extend)

26. Blocked response + pool configured → retry uses the next pool entry's credentials, not a re-templated username

### `tests/conftest.py`

27. Autouse fixture clears all `PROXY_*` / `WEBSHARE_*` env vars before each test, so local `.env` proxy configuration never leaks into test runs — tests opt in via `monkeypatch.setenv`

---

## Crawl4AI Native Integration (Rev 4)

`ManagedProxySession` now uses two pieces of Crawl4AI's native anti-bot/proxy surface directly, rather than reimplementing them:

- `crawl4ai.RoundRobinProxyStrategy` — owns pool-position tracking for the static-pool backend (`get_proxy_for_session(domain)` / `release_session(domain)`), replacing the hand-rolled `proxy_index` counter.
- `crawl4ai.antibot_detector.is_blocked` — backs `_is_blocked`/`_block_reason` in `crawler.py`, replacing the 3-marker hardcoded CAPTCHA heuristic.

Still not used, by design:

```python
proxy_rotation_strategy    = None  # set on CrawlerRunConfig — we call get_proxy_for_session ourselves instead, since
                                    # ManagedProxySession needs to layer domain pacing and the rotate-after-N threshold
                                    # on top, which CrawlerRunConfig's own rotation hook doesn't support
proxy_session_id           = None
proxy_session_ttl          = None
proxy_session_auto_release = False
max_retries (native)       = 0     # native's retry loop has no backoff/pacing between attempts; our own
                                    # _fetch_managed_proxy loop owns backoff, Retry-After handling, and the
                                    # separate transient-vs-block retry budgets
```

`ManagedProxySession` still owns rotation end-to-end for both backends — it injects one `ProxyConfig`-derived `ProxyCredentials` per attempt via `acquire_credentials`, using native primitives only for the parts that have no pacing/backoff requirement (pool position, anti-bot pattern matching).
