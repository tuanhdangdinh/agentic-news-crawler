# Design: ManagedProxySession — Job-Scoped Proxy Session Manager

**Date:** 2026-06-15
**Status:** Approved

---

## Overview

Add opt-in proxy support to the crawl engine. When `PROXY_URL` is set, every fetch is routed through a username-encoded sticky session scoped to the crawl job and the target domain. When `PROXY_URL` is absent, current behaviour is preserved exactly.

Proxy credentials are never exposed to `CrawlRequest`, the Gradio package, API response payloads, or logs.

---

## Architecture

```
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
                       ├─ seconds_until_ready(domain) → sleep if needed
                       ├─ get_credentials(domain) → ProxyCredentials | None
                       ├─ cfg.clone(proxy_config=creds.to_dict())
                       ├─ arun(url, config=cfg_for_attempt)
                       ├─ record_request(domain)
                       └─ blocked? → rotate(domain) → backoff → retry once
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

Dataclass: `session_id: str` (UUID4 hex), `request_count: int`, `last_request_at: float` (monotonic timestamp, set on each `record_request` call).

### `ManagedProxySession`

Job-scoped. One instance per `execute()` invocation.

State:
- `_settings: ProxySettings`
- `_sessions: dict[str, _DomainSession]` — keyed on normalised domain (`netloc` lowercased, `www.` stripped)
- `_lock: asyncio.Lock`

All public methods are `async` and acquire `_lock`. The lock is never held during `arun`, `asyncio.sleep`, or any I/O.

#### Public API

```python
async def get_credentials(domain: str) -> ProxyCredentials | None
```
Returns `None` if `settings.enabled` is `False`. Otherwise returns `ProxyCredentials` using the current sticky session for `domain`, creating a new `_DomainSession` (UUID4 hex session ID) on first visit.

Username is constructed as `settings.username_template.format(session_id=session.session_id)`.

```python
async def rotate(domain: str) -> ProxyCredentials | None
```
Retires the current session for `domain`. Generates a new UUID4 hex session ID and resets `request_count` to 0. Returns credentials for the new session, or `None` if not enabled.

```python
async def record_request(domain: str) -> None
```
Increments `request_count` and updates `last_request_at` to `monotonic()`. If `request_count >= settings.rotate_after_requests`, performs an in-place rotation without releasing the lock. To avoid re-entrancy, rotation logic is extracted into a private `_rotate_unlocked(domain)` method that assumes the lock is already held; `rotate()` acquires the lock then calls `_rotate_unlocked`; `record_request()` calls `_rotate_unlocked` directly.

```python
async def seconds_until_ready(domain: str) -> float
```
Returns `max(0.0, settings.domain_delay - (monotonic() - last_request_at))` for a previously-seen domain. Returns `0.0` for a first visit or when not enabled.

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
# runner.py
async def execute(request, state) -> dict          # unchanged — creates session internally

# agent.py
async def run_agent(seed_url, config, state=None,
                    *, proxy_session: ManagedProxySession | None = None) -> CrawlState

# crawler.py
async def fetch_page(url, css_selector=None,
                     *, article_body=True,
                     proxy_session: ManagedProxySession | None = None) -> PageResult

async def _fetch_with_retries(url, cfg,
                              *, proxy_session: ManagedProxySession | None = None) -> PageResult
```

Existing callers pass nothing; the no-proxy path is the default.

### `_BROWSER_CFG` unchanged

Proxy credentials are injected per-attempt via `cfg.clone(proxy_config=creds.to_dict())`. `_BROWSER_CFG` and `_make_cfg` are not modified.

---

## Retry Policy in `_fetch_with_retries`

```
entry:
  domain = normalised netloc of url
  if proxy_session:
    wait = await proxy_session.seconds_until_ready(domain)
    if wait > 0: await asyncio.sleep(wait)

  already_rotated = False

per-attempt loop (existing max_retries structure):
  creds = await proxy_session.get_credentials(domain) if proxy_session else None
  cfg_for_attempt = cfg.clone(proxy_config=creds.to_dict()) if creds else cfg
  result = await crawler.arun(url=url, config=cfg_for_attempt)
  await proxy_session.record_request(domain)   # every attempt, including fallback

  if blocked(result):                          # 403, 429, or CAPTCHA
    if already_rotated:
      return PageResult(success=False, error="proxy_blocked")
    new_creds = await proxy_session.rotate(domain)
    backoff = retry_after_header(result) if 429 else settings.block_backoff
    await asyncio.sleep(backoff)
    already_rotated = True
    continue                                   # retry with new credentials

  if 5xx or exception:
    # existing exponential backoff, same credentials (no rotation)
    await asyncio.sleep(2 ** attempt)
    continue

  return PageResult(success=True, ...)
```

The existing same-proxy 429 retry path is removed. 429 now enters the rotation branch.

---

## CAPTCHA Detection

`_is_captcha_response(result: CrawlResult) -> bool` in `crawler.py`. Checks applied cheapest-first:

1. Title (lowercased) contains any of: `"just a moment"`, `"verify you are human"`, `"bot detected"`, `"unusual traffic"`, `"access denied"`
2. HTML contains `id="cf-challenge-running"` or `class="cf-browser-verification"`
3. HTML contains `data-sitekey` attribute (reCAPTCHA / hCaptcha mount)
4. Script or iframe `src` contains `recaptcha.net`, `hcaptcha.com`, or `/cdn-cgi/challenge`

A plain 403 without any of the above does **not** set the CAPTCHA flag. Both plain-403 and CAPTCHA responses enter the same rotation branch — the distinction is logged but does not affect policy.

---

## Per-Domain Delay

`seconds_until_ready(domain)` is called once per URL, before the attempt loop. It reads `_DomainSession.last_request_at` and computes remaining delay against `settings.domain_delay`. The sleep happens in `_fetch_with_retries`; `ManagedProxySession` never sleeps.

---

## Security

- `ProxyCredentials.password` is excluded from `__repr__` and `__str__`.
- Log statements include session ID hash (`session_id[:8]`), domain, rotation reason, and request count only.
- `ProxyCredentials` is not added to any Pydantic model that could be serialised into a `PageResult`, `CrawlRequest`, or API response.

---

## Environment Variables

All variables are operator-only. None appear in `CrawlRequest`, `AgentConfig`, or the Gradio package.

| Variable | Default | Description |
|---|---|---|
| `PROXY_URL` | — | Proxy server URL. Proxy disabled if absent. |
| `PROXY_USERNAME_TEMPLATE` | `"user-session-{session_id}"` | Provider username pattern. |
| `PROXY_PASSWORD` | — | Proxy password. |
| `PROXY_ROTATE_AFTER_REQUESTS` | `20` | Rotate session after this many attempts. |
| `PROXY_DOMAIN_DELAY_SECONDS` | `2` | Minimum seconds between requests to the same domain. |
| `PROXY_BLOCK_BACKOFF_SECONDS` | `30` | Sleep after a blocking response before rotating retry. |

---

## Tests

### `tests/test_proxy.py` (new — unit, no network)

1. `ProxySettings.from_env()` → `enabled=False` when `PROXY_URL` absent
2. `get_credentials(domain)` → `None` when not enabled
3. First `get_credentials(domain)` → creates session with UUID4 hex session ID
4. Second `get_credentials(same_domain)` → returns same session ID
5. `get_credentials(different_domain)` → separate session ID
6. `rotate(domain)` → new session ID, different from previous
7. `record_request` × N → auto-rotates at threshold
8. `seconds_until_ready` → `0.0` on first visit; `> 0` on immediate second visit
9. Concurrent `get_credentials` calls → consistent state (no race)
10. `repr(ProxyCredentials(...))` → password absent

### `tests/test_crawler_fetch_page.py` (extend)

11. 403 + no proxy → no rotation, `PageResult(success=False)`
12. 403 + proxy → `rotate` called once, retry attempted
13. Second block after rotation → `PageResult(success=False, error="proxy_blocked")`, no further rotation
14. 429 with `Retry-After: 5` → sleeps ~5 s, rotates
15. CAPTCHA HTML (`#cf-challenge-running`) → rotation triggered
16. Plain 403 without CAPTCHA markers → rotation triggered, `_is_captcha_response` returns `False`
17. 5xx → exponential backoff, `rotate` never called
18. `record_request` called for every attempt including article-to-full-page fallback
19. Domain delay: second fetch to same domain sleeps `PROXY_DOMAIN_DELAY_SECONDS`
20. `PageResult` contains no proxy credential fields

### `tests/test_runner.py` (extend)

21. Direct-fetch and agent paths receive the same `ManagedProxySession` instance from `execute()`

---

## Crawl4AI Fields Left Unset

```python
proxy_rotation_strategy = None
proxy_session_id        = None
proxy_session_ttl       = None
proxy_session_auto_release = False
```

A future static proxy-pool backend could use Crawl4AI's native rotation strategy. The current managed-provider backend injects one dynamically generated `ProxyConfig` per attempt.
