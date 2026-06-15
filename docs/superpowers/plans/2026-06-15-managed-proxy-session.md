# ManagedProxySession Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in, job-scoped proxy support that routes fetches through username-encoded sticky sessions per domain, with autonomous rotation on blocking responses and request thresholds.

**Architecture:** A new `proxy.py` module owns all proxy state (`ProxySettings`, `ProxyCredentials`, `ManagedProxySession`). `execute()` creates one `ManagedProxySession` per invocation and threads it via new keyword-only `proxy_session` params through `run_agent → fetch_page → _fetch_with_retries`. A new private `_fetch_managed_proxy` in `crawler.py` implements the two-counter retry loop; the existing no-proxy path is untouched.

**Tech Stack:** Python `asyncio`, `uuid`, `dataclasses`; Crawl4AI `CrawlerRunConfig.proxy_config` + `.clone()`; `pytest-asyncio` (`asyncio_mode = "auto"` in root `pyproject.toml`).

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `packages/engine/src/crawl_engine/proxy.py` | `ProxySettings`, `ProxyCredentials`, `_DomainSession`, `ManagedProxySession` |
| Create | `packages/engine/tests/test_proxy.py` | Unit tests for all proxy module types |
| Modify | `packages/engine/src/crawl_engine/crawler.py` | Add `_retry_after`, `_build_success_result`, `_is_captcha_response`, `_is_blocked`, `_fetch_managed_proxy`; update `_fetch_with_retries` and `fetch_page` |
| Modify | `packages/engine/tests/test_crawler_fetch_page.py` | Tests for CAPTCHA detection and proxy retry policy |
| Modify | `packages/engine/src/crawl_engine/agent.py` | Add `proxy_session` param to `run_agent`, thread to `fetch_page` |
| Modify | `packages/engine/src/crawl_engine/runner.py` | Create `ManagedProxySession` in `execute()`, thread to both paths |
| Modify | `packages/engine/tests/test_runner.py` | Test that `execute()` passes a `ManagedProxySession` when `PROXY_URL` is set |

---

## Task 1: ProxySettings + ProxyCredentials

**Files:**

- Create: `packages/engine/src/crawl_engine/proxy.py`
- Create: `packages/engine/tests/test_proxy.py`

- [ ] **Step 1: Write failing tests**

```python
# packages/engine/tests/test_proxy.py
"""Unit tests for crawl_engine.proxy."""

from __future__ import annotations

import os

import pytest
from crawl_engine.proxy import ProxyCredentials, ProxySettings


def test_proxy_settings_disabled_when_url_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROXY_URL", raising=False)
    settings = ProxySettings.from_env()
    assert settings.enabled is False


def test_proxy_settings_enabled_when_url_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY_URL", "http://proxy.example.com:8080")
    monkeypatch.setenv("PROXY_PASSWORD", "secret")
    settings = ProxySettings.from_env()
    assert settings.enabled is True
    assert settings.url == "http://proxy.example.com:8080"
    assert settings.rotate_after_requests == 20
    assert settings.domain_delay == 2.0
    assert settings.block_backoff == 30.0


def test_proxy_credentials_to_dict() -> None:
    creds = ProxyCredentials(server="http://p:8080", username="user", password="pass")
    assert creds.to_dict() == {"server": "http://p:8080", "username": "user", "password": "pass"}


def test_proxy_credentials_repr_omits_password() -> None:
    creds = ProxyCredentials(server="http://p:8080", username="user", password="s3cr3t")
    assert "s3cr3t" not in repr(creds)
    assert "s3cr3t" not in str(creds)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd packages/engine && uv run pytest tests/test_proxy.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'crawl_engine.proxy'`

- [ ] **Step 3: Create `proxy.py` with data types**

```python
# packages/engine/src/crawl_engine/proxy.py
"""Job-scoped proxy session manager for username-encoded sticky sessions."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProxySettings:
    """Operator-only proxy configuration read from environment variables."""

    enabled: bool
    url: str
    username_template: str
    password: str
    rotate_after_requests: int
    domain_delay: float
    block_backoff: float

    @classmethod
    def from_env(cls) -> ProxySettings:
        url = os.environ.get("PROXY_URL", "")
        return cls(
            enabled=bool(url),
            url=url,
            username_template=os.environ.get(
                "PROXY_USERNAME_TEMPLATE", "user-session-{session_id}"
            ),
            password=os.environ.get("PROXY_PASSWORD", ""),
            rotate_after_requests=int(os.environ.get("PROXY_ROTATE_AFTER_REQUESTS", "20")),
            domain_delay=float(os.environ.get("PROXY_DOMAIN_DELAY_SECONDS", "2")),
            block_backoff=float(os.environ.get("PROXY_BLOCK_BACKOFF_SECONDS", "30")),
        )


@dataclass(frozen=True)
class ProxyCredentials:
    """Proxy server credentials. Password is excluded from repr and str."""

    server: str
    username: str
    password: str

    def to_dict(self) -> dict[str, str]:
        return {"server": self.server, "username": self.username, "password": self.password}

    def __repr__(self) -> str:
        return (
            f"ProxyCredentials(server={self.server!r}, username={self.username!r}, password='***')"
        )

    def __str__(self) -> str:
        return self.__repr__()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd packages/engine && uv run pytest tests/test_proxy.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/crawl_engine/proxy.py packages/engine/tests/test_proxy.py
git commit -m "feat: add ProxySettings and ProxyCredentials"
```

---

## Task 2: ManagedProxySession — acquire_credentials

**Files:**

- Modify: `packages/engine/src/crawl_engine/proxy.py`
- Modify: `packages/engine/tests/test_proxy.py`

- [ ] **Step 1: Write failing tests**

Append to `packages/engine/tests/test_proxy.py`:

```python
import asyncio

import pytest
from crawl_engine.proxy import ManagedProxySession, ProxyCredentials, ProxySettings


@pytest.fixture
def proxy_settings() -> ProxySettings:
    return ProxySettings(
        enabled=True,
        url="http://proxy.example.com:8080",
        username_template="user-session-{session_id}",
        password="testpass",
        rotate_after_requests=20,
        domain_delay=2.0,
        block_backoff=30.0,
    )


async def test_acquire_credentials_disabled_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROXY_URL", raising=False)
    settings = ProxySettings.from_env()
    session = ManagedProxySession(settings)
    creds, wait = await session.acquire_credentials("example.com")
    assert creds is None
    assert wait == 0.0


async def test_acquire_credentials_first_visit(proxy_settings: ProxySettings) -> None:
    session = ManagedProxySession(proxy_settings)
    creds, wait = await session.acquire_credentials("example.com")
    assert isinstance(creds, ProxyCredentials)
    assert wait == 0.0
    assert creds.server == "http://proxy.example.com:8080"
    assert creds.username.startswith("user-session-")
    assert len(creds.username.split("-")[-1]) == 32  # UUID4 hex suffix


async def test_acquire_credentials_sticky_same_domain(proxy_settings: ProxySettings) -> None:
    session = ManagedProxySession(proxy_settings)
    creds1, _ = await session.acquire_credentials("example.com")
    creds2, _ = await session.acquire_credentials("example.com")
    assert creds1 is not None and creds2 is not None
    assert creds1.username == creds2.username


async def test_acquire_credentials_separate_sessions_per_domain(
    proxy_settings: ProxySettings,
) -> None:
    session = ManagedProxySession(proxy_settings)
    creds_a, _ = await session.acquire_credentials("site-a.com")
    creds_b, _ = await session.acquire_credentials("site-b.com")
    assert creds_a is not None and creds_b is not None
    assert creds_a.username != creds_b.username


async def test_acquire_credentials_domain_delay(proxy_settings: ProxySettings) -> None:
    session = ManagedProxySession(proxy_settings)
    _, wait1 = await session.acquire_credentials("example.com")
    _, wait2 = await session.acquire_credentials("example.com")
    assert wait1 == 0.0
    assert wait2 > 0.0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd packages/engine && uv run pytest tests/test_proxy.py -v -k "acquire" 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'ManagedProxySession'`

- [ ] **Step 3: Add `_DomainSession` and `ManagedProxySession` to `proxy.py`**

Add after the `ProxyCredentials` class in `packages/engine/src/crawl_engine/proxy.py`:

```python
import asyncio
from time import monotonic
from uuid import uuid4


@dataclass
class _DomainSession:
    session_id: str
    request_count: int
    last_request_at: float


class ManagedProxySession:
    """Job-scoped sticky proxy session manager keyed on normalised domain."""

    def __init__(self, settings: ProxySettings) -> None:
        self._settings = settings
        self._sessions: dict[str, _DomainSession] = {}
        self._lock = asyncio.Lock()

    @property
    def settings(self) -> ProxySettings:
        return self._settings

    async def acquire_credentials(
        self, domain: str
    ) -> tuple[ProxyCredentials | None, float]:
        """Atomically issue credentials for domain, computing delay from previous request.

        Returns:
            (credentials, seconds_to_wait). credentials is None when proxy is disabled.
            Caller must sleep seconds_to_wait before using the credentials.
        """
        if not self._settings.enabled:
            return None, 0.0

        async with self._lock:
            now = monotonic()
            ds = self._sessions.get(domain)

            if ds is None:
                wait = 0.0
                ds = _DomainSession(session_id=uuid4().hex, request_count=0, last_request_at=0.0)
                self._sessions[domain] = ds
            else:
                wait = max(0.0, self._settings.domain_delay - (now - ds.last_request_at))
                if ds.request_count >= self._settings.rotate_after_requests:
                    self._rotate_unlocked(domain, reason="threshold")
                    ds = self._sessions[domain]

            ds.request_count += 1
            ds.last_request_at = monotonic()

            username = self._settings.username_template.format(session_id=ds.session_id)
            return (
                ProxyCredentials(
                    server=self._settings.url,
                    username=username,
                    password=self._settings.password,
                ),
                wait,
            )

    def _rotate_unlocked(self, domain: str, reason: str) -> None:
        """Replace the current domain session. Caller must hold _lock."""
        import structlog

        log = structlog.get_logger(__name__)
        old = self._sessions.get(domain)
        old_count = old.request_count if old else 0
        old_prefix = old.session_id[:8] if old else "none"
        new_session = _DomainSession(session_id=uuid4().hex, request_count=0, last_request_at=0.0)
        self._sessions[domain] = new_session
        log.info(
            "proxy session rotated",
            domain=domain,
            reason=reason,
            old_session_prefix=old_prefix,
            new_session_prefix=new_session.session_id[:8],
            requests_on_old=old_count,
        )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd packages/engine && uv run pytest tests/test_proxy.py -v -k "acquire or disabled or first or sticky or separate or delay"
```

Expected: all 5 new tests PASS (plus 4 from Task 1).

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/crawl_engine/proxy.py packages/engine/tests/test_proxy.py
git commit -m "feat: add ManagedProxySession with atomic acquire_credentials"
```

---

## Task 3: ManagedProxySession — rotate + threshold auto-rotation + concurrency

**Files:**

- Modify: `packages/engine/src/crawl_engine/proxy.py`
- Modify: `packages/engine/tests/test_proxy.py`

- [ ] **Step 1: Write failing tests**

Append to `packages/engine/tests/test_proxy.py`:

```python
async def test_rotate_creates_new_session_id(proxy_settings: ProxySettings) -> None:
    session = ManagedProxySession(proxy_settings)
    creds_before, _ = await session.acquire_credentials("example.com")
    await session.rotate("example.com", reason="test")
    creds_after, _ = await session.acquire_credentials("example.com")
    assert creds_before is not None and creds_after is not None
    assert creds_before.username != creds_after.username


async def test_auto_rotate_at_threshold() -> None:
    settings = ProxySettings(
        enabled=True,
        url="http://proxy.example.com:8080",
        username_template="user-session-{session_id}",
        password="pass",
        rotate_after_requests=3,
        domain_delay=0.0,
        block_backoff=0.0,
    )
    session = ManagedProxySession(settings)
    usernames = []
    for _ in range(4):
        c, _ = await session.acquire_credentials("example.com")
        assert c is not None
        usernames.append(c.username)
    # Acquisitions 1-3 use the same session; acquisition 4 triggers auto-rotation.
    assert usernames[0] == usernames[1] == usernames[2]
    assert usernames[3] != usernames[0]


async def test_concurrent_acquire_consistent(proxy_settings: ProxySettings) -> None:
    session = ManagedProxySession(proxy_settings)
    results = await asyncio.gather(
        *[session.acquire_credentials("example.com") for _ in range(5)]
    )
    usernames = [r[0].username for r in results if r[0] is not None]
    assert len(usernames) == 5
    assert len(set(usernames)) == 1  # all share the same initial session
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd packages/engine && uv run pytest tests/test_proxy.py -v -k "rotate or threshold or concurrent" 2>&1 | head -20
```

Expected: `AttributeError: 'ManagedProxySession' object has no attribute 'rotate'`

- [ ] **Step 3: Add `rotate` method to `ManagedProxySession`**

Add after `_rotate_unlocked` in the `ManagedProxySession` class in `proxy.py`:

```python
    async def rotate(self, domain: str, *, reason: str) -> None:
        """Retire the current session for domain. Next acquire_credentials creates a new one."""
        async with self._lock:
            self._rotate_unlocked(domain, reason=reason)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd packages/engine && uv run pytest tests/test_proxy.py -v
```

Expected: all 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/crawl_engine/proxy.py packages/engine/tests/test_proxy.py
git commit -m "feat: add rotate and threshold auto-rotation to ManagedProxySession"
```

---

## Task 4: CAPTCHA detection and block helpers in crawler.py

**Files:**

- Modify: `packages/engine/src/crawl_engine/crawler.py`
- Modify: `packages/engine/tests/test_crawler_fetch_page.py`

- [ ] **Step 1: Write failing tests**

Append to `packages/engine/tests/test_crawler_fetch_page.py`:

```python
from crawl_engine.crawler import _is_blocked, _is_captcha_response


def _blocked_result(
    status_code: int = 403,
    html: str = "",
    title: str = "Forbidden",
) -> MagicMock:
    result = MagicMock()
    result.success = False
    result.status_code = status_code
    result.error_message = f"HTTP {status_code}"
    result.url = "https://example.com"
    result.html = html
    result.metadata = {"title": title}
    result.response_headers = {}
    result.markdown = None
    result.links = {}
    return result


# --- _is_captcha_response ---

def test_captcha_cf_challenge_running() -> None:
    result = _blocked_result(html='<div id="cf-challenge-running"></div>')
    assert _is_captcha_response(result) is True


def test_captcha_cf_browser_verification() -> None:
    result = _blocked_result(html='<div class="cf-browser-verification"></div>')
    assert _is_captcha_response(result) is True


def test_captcha_cf_challenge_body() -> None:
    result = _blocked_result(html='<div class="cf-challenge-body"></div>')
    assert _is_captcha_response(result) is True


def test_captcha_403_just_a_moment() -> None:
    result = _blocked_result(status_code=403, title="Just a moment...")
    assert _is_captcha_response(result) is True


def test_captcha_403_verify_you_are_human() -> None:
    result = _blocked_result(status_code=403, title="Verify you are human")
    assert _is_captcha_response(result) is True


def test_not_captcha_data_sitekey_alone() -> None:
    result = _blocked_result(html='<form data-sitekey="abc123"><button>Submit</button></form>')
    assert _is_captcha_response(result) is False


def test_not_captcha_plain_403() -> None:
    result = _blocked_result(status_code=403, html="<html>Forbidden</html>", title="Forbidden")
    assert _is_captcha_response(result) is False


def test_not_captcha_200_with_recaptcha_widget() -> None:
    result = _blocked_result(
        status_code=200,
        html='<div data-sitekey="key"><script src="recaptcha.net/api.js"></script></div>',
        title="Comment on post",
    )
    assert _is_captcha_response(result) is False


# --- _is_blocked ---

def test_is_blocked_403() -> None:
    assert _is_blocked(_blocked_result(403)) is True


def test_is_blocked_429() -> None:
    assert _is_blocked(_blocked_result(429)) is True


def test_is_blocked_captcha_200() -> None:
    result = _blocked_result(status_code=200, html='<div id="cf-challenge-running"></div>')
    assert _is_blocked(result) is True


def test_not_blocked_200() -> None:
    result = MagicMock()
    result.status_code = 200
    result.html = ""
    result.metadata = {}
    assert _is_blocked(result) is False


def test_not_blocked_500() -> None:
    result = _blocked_result(500)
    assert _is_blocked(result) is False
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd packages/engine && uv run pytest tests/test_crawler_fetch_page.py -v -k "captcha or blocked" 2>&1 | head -20
```

Expected: `ImportError: cannot import name '_is_blocked'`

- [ ] **Step 3: Add helpers to `crawler.py`**

In `packages/engine/src/crawl_engine/crawler.py`, add the following three functions **before** `_fetch_with_retries` (after `_has_usable_scoped_markdown`):

```python
def _retry_after(result) -> float:
    """Extract Retry-After seconds from a response."""
    resp_hdrs = getattr(result, "response_headers", {}) or {}
    raw = resp_hdrs.get("retry-after") or resp_hdrs.get("Retry-After") or "60"
    try:
        return max(float(raw), 0.0)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max((retry_at - datetime.now(UTC)).total_seconds(), 0.0)
        except (TypeError, ValueError, OverflowError):
            return 60.0


def _is_captcha_response(result) -> bool:
    """Return True only when strong challenge signals are present."""
    html = result.html or ""
    if (
        'id="cf-challenge-running"' in html
        or "cf-browser-verification" in html
        or "cf-challenge-body" in html
    ):
        return True
    status = result.status_code or 0
    if status == 403:
        metadata = result.metadata or {}
        title = (metadata.get("title") or "").lower()
        if "just a moment" in title or "verify you are human" in title:
            return True
    return False


def _is_blocked(result) -> bool:
    """Return True for 403, 429, or a detected CAPTCHA challenge."""
    status = result.status_code or 0
    return status in (403, 429) or _is_captcha_response(result)
```

Also extract `_build_success_result` from the success path inside `_fetch_with_retries`. Insert **before** `_fetch_with_retries`:

```python
def _build_success_result(url: str, result, fetch_time: float) -> PageResult:
    """Build a PageResult from a successful CrawlResult."""
    md = result.markdown
    markdown = (md.fit_markdown or md.raw_markdown) if md else ""
    raw_markdown = md.raw_markdown if md else None
    internal, external = _extract_links(result.links or {})
    metadata = result.metadata or {}
    byline_author = None
    if looks_like_article_url(result.url or url):
        byline_author = _extract_byline_author(result.html)
    if byline_author:
        metadata["byline_author"] = byline_author
    title = metadata.get("title") or metadata.get("og:title")
    resp_hdrs = getattr(result, "response_headers", {}) or {}
    logger.info(
        "fetch ok",
        url=url,
        status=result.status_code,
        chars=len(markdown),
        links=len(internal),
        time=fetch_time,
    )
    return PageResult(
        url=url,
        final_url=result.url,
        status_code=result.status_code,
        title=title,
        markdown=markdown,
        raw_markdown=raw_markdown,
        html=result.html,
        links_internal=internal,
        links_external=external,
        metadata=metadata,
        headers=resp_hdrs,
        fetch_time=fetch_time,
        success=True,
        error=None,
    )
```

Then replace the success path in `_fetch_with_retries` (lines 331–368 in the original) with a single call:

```python
            return _build_success_result(url, result, fetch_time)
```

And replace the 429 handling block (lines 285–305) with:

```python
                if status == 429:
                    retry_after = _retry_after(result)
                    logger.warning(
                        "fetch 429", url=url, retry_after=retry_after, attempt=attempt + 1
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(retry_after)
                        continue
```

- [ ] **Step 4: Run all tests to confirm passing**

```bash
cd packages/engine && uv run pytest tests/test_crawler_fetch_page.py -v
```

Expected: all tests PASS (including pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/crawl_engine/crawler.py packages/engine/tests/test_crawler_fetch_page.py
git commit -m "feat: add _is_captcha_response, _is_blocked, _retry_after, _build_success_result"
```

---

## Task 5: _fetch_managed_proxy + _fetch_with_retries dispatch

**Files:**

- Modify: `packages/engine/src/crawl_engine/crawler.py`
- Modify: `packages/engine/tests/test_crawler_fetch_page.py`

- [ ] **Step 1: Write failing proxy retry tests**

Append to `packages/engine/tests/test_crawler_fetch_page.py`:

```python
from unittest.mock import AsyncMock, patch

from crawl_engine.proxy import ManagedProxySession, ProxyCredentials, ProxySettings


def _make_proxy_session() -> MagicMock:
    """Mock ManagedProxySession returning fixed credentials with zero delay."""
    session = MagicMock(spec=ManagedProxySession)
    default = (
        ProxyCredentials(server="http://proxy:8080", username="user-abc123", password="pass"),
        0.0,
    )
    session.acquire_credentials = AsyncMock(return_value=default)
    session.rotate = AsyncMock()
    session.settings = ProxySettings(
        enabled=True,
        url="http://proxy:8080",
        username_template="user-session-{session_id}",
        password="pass",
        rotate_after_requests=20,
        domain_delay=0.0,
        block_backoff=0.0,
    )
    return session


def _multi_crawler(*results: MagicMock) -> MagicMock:
    """Crawler mock that returns successive results on each arun() call."""
    crawler = MagicMock()
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=None)
    crawler.arun = AsyncMock(side_effect=list(results))
    return crawler


@pytest.mark.asyncio
async def test_403_no_proxy_no_rotation() -> None:
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls:
        mock_cls.return_value = _crawler_context(_crawl_result(success=False, status_code=403))
        result = await fetch_page("https://example.com")
    assert result.success is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_403_with_proxy_rotates_once_then_succeeds() -> None:
    proxy = _make_proxy_session()
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ):
        mock_cls.return_value = _multi_crawler(
            _blocked_result(403),
            _crawl_result(),
        )
        result = await fetch_page("https://example.com", proxy_session=proxy)
    assert result.success is True
    proxy.rotate.assert_awaited_once_with("example.com", reason="http_403")


@pytest.mark.asyncio
async def test_second_block_after_rotation_returns_proxy_blocked() -> None:
    proxy = _make_proxy_session()
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ):
        mock_cls.return_value = _multi_crawler(
            _blocked_result(403),
            _blocked_result(403),
        )
        result = await fetch_page("https://example.com", proxy_session=proxy)
    assert result.success is False
    assert result.error == "proxy_blocked"
    assert proxy.rotate.await_count == 1


@pytest.mark.asyncio
async def test_429_with_retry_after_rotates() -> None:
    proxy = _make_proxy_session()
    blocked = _blocked_result(429)
    blocked.response_headers = {"Retry-After": "5"}
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ) as mock_sleep:
        mock_cls.return_value = _multi_crawler(blocked, _crawl_result())
        result = await fetch_page("https://example.com", proxy_session=proxy)
    assert result.success is True
    proxy.rotate.assert_awaited_once_with("example.com", reason="http_429")
    mock_sleep.assert_awaited()


@pytest.mark.asyncio
async def test_captcha_triggers_rotation() -> None:
    proxy = _make_proxy_session()
    captcha = _blocked_result(403, html='<div id="cf-challenge-running"></div>')
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ):
        mock_cls.return_value = _multi_crawler(captcha, _crawl_result())
        result = await fetch_page("https://example.com", proxy_session=proxy)
    assert result.success is True
    proxy.rotate.assert_awaited_once_with("example.com", reason="captcha")


@pytest.mark.asyncio
async def test_data_sitekey_alone_is_plain_403_not_captcha() -> None:
    proxy = _make_proxy_session()
    plain = _blocked_result(403, html='<form data-sitekey="key"></form>', title="Forbidden")
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ):
        mock_cls.return_value = _multi_crawler(plain, _crawl_result())
        result = await fetch_page("https://example.com", proxy_session=proxy)
    assert result.success is True
    proxy.rotate.assert_awaited_once_with("example.com", reason="http_403")


@pytest.mark.asyncio
async def test_5xx_uses_transient_retry_no_rotation() -> None:
    proxy = _make_proxy_session()
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ):
        mock_cls.return_value = _multi_crawler(
            _crawl_result(success=False, status_code=500),
            _crawl_result(),
        )
        result = await fetch_page("https://example.com", proxy_session=proxy)
    assert result.success is True
    proxy.rotate.assert_not_awaited()


@pytest.mark.asyncio
async def test_block_rotation_independent_of_transient_retries() -> None:
    """A 5xx transient retry followed by a 403 block still gets one rotation."""
    proxy = _make_proxy_session()
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ):
        mock_cls.return_value = _multi_crawler(
            _crawl_result(success=False, status_code=500),
            _blocked_result(403),
            _crawl_result(),
        )
        result = await fetch_page("https://example.com", proxy_session=proxy)
    assert result.success is True
    proxy.rotate.assert_awaited_once()


@pytest.mark.asyncio
async def test_domain_delay_respected() -> None:
    """acquire_credentials returns wait > 0 on second domain call; fetch_page sleeps."""
    creds = ProxyCredentials(server="http://p:8080", username="u", password="pw")
    proxy = MagicMock(spec=ManagedProxySession)
    proxy.acquire_credentials = AsyncMock(side_effect=[(creds, 0.0), (creds, 1.5)])
    proxy.rotate = AsyncMock()
    proxy.settings = ProxySettings(
        enabled=True, url="http://p:8080", username_template="u-{session_id}",
        password="pw", rotate_after_requests=20, domain_delay=2.0, block_backoff=0.0,
    )
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ) as mock_sleep:
        mock_cls.return_value = _crawler_context(_crawl_result())
        await fetch_page("https://example.com", proxy_session=proxy)
        mock_cls.return_value = _crawler_context(_crawl_result())
        await fetch_page("https://example.com", proxy_session=proxy)
    assert any(call.args and call.args[0] == pytest.approx(1.5) for call in mock_sleep.await_args_list)


@pytest.mark.asyncio
async def test_page_result_contains_no_proxy_credentials() -> None:
    proxy = _make_proxy_session()
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ):
        mock_cls.return_value = _crawler_context(_crawl_result())
        result = await fetch_page("https://cafef.vn/bai-viet-123456789.chn", proxy_session=proxy)
    result_dict = result.model_dump()
    assert "password" not in result_dict
    assert "proxy" not in str(result_dict).lower()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd packages/engine && uv run pytest tests/test_crawler_fetch_page.py -v -k "proxy or rotation or delay or captcha or blocked" 2>&1 | head -30
```

Expected: failures because `fetch_page` does not yet accept `proxy_session`.

- [ ] **Step 3: Add `_fetch_managed_proxy` and update `_fetch_with_retries`**

At the top of `packages/engine/src/crawl_engine/crawler.py`, add the import (after existing imports):

```python
from crawl_engine.proxy import ManagedProxySession
```

Add `_MAX_PROXY_TRANSIENT_RETRIES = 3` as a module-level constant after the existing constants.

Add `_fetch_managed_proxy` immediately before `_fetch_with_retries`:

```python
async def _fetch_managed_proxy(
    url: str, cfg: CrawlerRunConfig, proxy_session: ManagedProxySession
) -> PageResult:
    """Fetch with proxy — independent transient and block rotation counters."""
    domain = urlparse(url).netloc.removeprefix("www.")
    transient_retries = 0
    block_rotations = 0

    while True:
        t0 = time.monotonic()
        creds, wait = await proxy_session.acquire_credentials(domain)
        if wait > 0:
            await asyncio.sleep(wait)

        cfg_for_attempt = cfg.clone(proxy_config=creds.to_dict()) if creds else cfg
        try:
            async with AsyncWebCrawler(config=_BROWSER_CFG) as crawler:
                result = await crawler.arun(url=url, config=cfg_for_attempt)
            fetch_time = round(time.monotonic() - t0, 2)
        except Exception as exc:  # noqa: BLE001
            fetch_time = round(time.monotonic() - t0, 2)
            if transient_retries < _MAX_PROXY_TRANSIENT_RETRIES:
                transient_retries += 1
                backoff = 2**transient_retries
                logger.warning("fetch exception retrying", url=url, exc=str(exc), backoff=backoff)
                await asyncio.sleep(backoff)
                continue
            logger.warning("fetch exception", url=url, exc=str(exc))
            return PageResult(
                url=url, final_url=url, status_code=None, title=None,
                markdown="", fetch_time=fetch_time, success=False, error=str(exc),
            )

        status = result.status_code or 0

        if _is_blocked(result):
            if block_rotations >= 1:
                logger.warning("proxy blocked after rotation", url=url, status=status)
                return PageResult(
                    url=url, final_url=url, status_code=status, title=None,
                    markdown="", fetch_time=fetch_time, success=False, error="proxy_blocked",
                )
            reason = "captcha" if _is_captcha_response(result) else f"http_{status}"
            logger.warning("fetch blocked, rotating", url=url, status=status, reason=reason)
            await proxy_session.rotate(domain, reason=reason)
            backoff = (
                _retry_after(result)
                if status == 429
                else proxy_session.settings.block_backoff
            )
            await asyncio.sleep(backoff)
            block_rotations += 1
            continue

        if status >= 500:
            if transient_retries < _MAX_PROXY_TRANSIENT_RETRIES:
                transient_retries += 1
                backoff = 2**transient_retries
                logger.warning("fetch error retrying", status=status, url=url, backoff=backoff)
                await asyncio.sleep(backoff)
                continue
            logger.warning("fetch failed", url=url, status=status)
            return PageResult(
                url=url, final_url=url, status_code=status, title=None,
                markdown="", fetch_time=fetch_time, success=False, error=f"HTTP {status}",
            )

        if not result.success:
            error = result.error_message or f"HTTP {status}"
            logger.warning("fetch failed", url=url, status=status, error=error)
            return PageResult(
                url=url, final_url=url, status_code=status, title=None,
                markdown="", fetch_time=fetch_time, success=False, error=error,
            )

        return _build_success_result(url, result, fetch_time)
```

Update the `_fetch_with_retries` signature and add dispatch at the top:

```python
async def _fetch_with_retries(
    url: str,
    cfg: CrawlerRunConfig,
    *,
    proxy_session: ManagedProxySession | None = None,
) -> PageResult:
    """Run a single fetch with up to 3 retries on 5xx / exception."""
    if proxy_session is not None:
        return await _fetch_managed_proxy(url, cfg, proxy_session)

    max_retries = 3
    # ... rest of function body unchanged ...
```

- [ ] **Step 4: Run all crawler tests**

```bash
cd packages/engine && uv run pytest tests/test_crawler_fetch_page.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/crawl_engine/crawler.py packages/engine/tests/test_crawler_fetch_page.py
git commit -m "feat: add _fetch_managed_proxy and proxy_session dispatch in _fetch_with_retries"
```

---

## Task 6: Thread proxy_session through fetch_page, run_agent, and execute

**Files:**

- Modify: `packages/engine/src/crawl_engine/crawler.py` — `fetch_page` signature
- Modify: `packages/engine/src/crawl_engine/agent.py` — `run_agent` signature
- Modify: `packages/engine/src/crawl_engine/runner.py` — `execute` creates session
- Modify: `packages/engine/tests/test_runner.py`

- [ ] **Step 1: Write failing test**

Append to `packages/engine/tests/test_runner.py`:

```python
import os

from crawl_engine.proxy import ManagedProxySession


@pytest.mark.asyncio
async def test_execute_passes_managed_proxy_session_when_proxy_url_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROXY_URL", "http://proxy.example.com:8080")
    monkeypatch.setenv("PROXY_PASSWORD", "secret")

    captured: dict = {}

    async def fake_run_agent(seed, config, state=None, *, proxy_session=None):
        captured["proxy_session"] = proxy_session
        state.pages.append(_page())
        state.finish_reason = "done"

    request = CrawlRequest(seed_url="https://cafef.vn", goal="collect news")
    with patch("crawl_engine.runner.run_agent", side_effect=fake_run_agent):
        await execute(request, CrawlState())

    assert isinstance(captured.get("proxy_session"), ManagedProxySession)


@pytest.mark.asyncio
async def test_execute_no_proxy_session_when_proxy_url_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROXY_URL", raising=False)

    captured: dict = {}

    async def fake_run_agent(seed, config, state=None, *, proxy_session=None):
        captured["proxy_session"] = proxy_session
        state.pages.append(_page())
        state.finish_reason = "done"

    request = CrawlRequest(seed_url="https://cafef.vn", goal="collect news")
    with patch("crawl_engine.runner.run_agent", side_effect=fake_run_agent):
        await execute(request, CrawlState())

    assert captured.get("proxy_session") is None
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd packages/engine && uv run pytest tests/test_runner.py -v -k "proxy" 2>&1 | head -20
```

Expected: failure because `run_agent` does not accept `proxy_session`.

- [ ] **Step 3: Update `fetch_page` in `crawler.py`**

Change the signature of `fetch_page`:

```python
async def fetch_page(
    url: str,
    css_selector: str | None = None,
    *,
    article_body: bool = True,
    proxy_session: ManagedProxySession | None = None,
) -> PageResult:
```

Thread `proxy_session` to both `_fetch_with_retries` calls inside `fetch_page`:

```python
    page = await _fetch_with_retries(url, _make_cfg(css_selector, target_elements), proxy_session=proxy_session)

    if (
        (css_selector or target_elements)
        and page.success
        and not _has_usable_scoped_markdown(page.markdown)
    ):
        logger.warning("scoped fetch returned unusable markdown, retrying full page", url=url)
        page = await _fetch_with_retries(url, _RUN_CFG, proxy_session=proxy_session)
```

- [ ] **Step 4: Update `run_agent` in `agent.py`**

Change the function signature:

```python
async def run_agent(
    seed_url: str,
    config: AgentConfig,
    state: CrawlState | None = None,
    *,
    proxy_session: ManagedProxySession | None = None,
) -> CrawlState:
```

Add the import at the top of `agent.py` (with other imports):

```python
from crawl_engine.proxy import ManagedProxySession
```

Thread `proxy_session` at the `fetch_page` call site (line ~517):

```python
        page = await fetch_page(url, css_selector=config.css_selector or None, proxy_session=proxy_session)
```

- [ ] **Step 5: Update `execute` in `runner.py`**

Add import at the top of `runner.py`:

```python
from crawl_engine.proxy import ManagedProxySession, ProxySettings
```

Update `execute`:

```python
async def execute(request: CrawlRequest, state: CrawlState) -> dict:
    settings = ProxySettings.from_env()
    proxy_session: ManagedProxySession | None = (
        ManagedProxySession(settings) if settings.enabled else None
    )
    config = request.to_agent_config()
    seed = request.seed_url
    if not config.goal and not config.extract_prompt:
        page = await fetch_page(seed, css_selector=config.css_selector or None, proxy_session=proxy_session)
        return _result_payload([page], _direct_run_meta(seed, page))
    await run_agent(seed, config, state=state, proxy_session=proxy_session)
    return _result_payload(state.pages, _agent_run_meta(seed, config, state))
```

- [ ] **Step 6: Run all tests**

```bash
cd packages/engine && uv run pytest -v
```

Expected: all tests PASS with no regressions.

- [ ] **Step 7: Commit**

```bash
git add packages/engine/src/crawl_engine/crawler.py \
        packages/engine/src/crawl_engine/agent.py \
        packages/engine/src/crawl_engine/runner.py \
        packages/engine/tests/test_runner.py
git commit -m "feat: thread ManagedProxySession through fetch_page, run_agent, and execute"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| `ProxySettings` from env, `enabled=False` when URL absent | Task 1 |
| `ProxyCredentials` with `to_dict()`, password excluded from repr | Task 1 |
| `_DomainSession` internal type | Task 2 |
| `acquire_credentials` — atomic, sticky, delay, threshold rotation | Task 2–3 |
| `rotate(domain, *, reason)` — retires session | Task 3 |
| `_rotate_unlocked` re-entrancy pattern | Task 2 |
| `settings` property on `ManagedProxySession` | Task 2 |
| `_is_captcha_response` strong markers + phrase+403 | Task 4 |
| `_is_blocked` | Task 4 |
| `_retry_after` extracted helper | Task 4 |
| `_build_success_result` extracted helper | Task 4 |
| `_fetch_managed_proxy` — two-counter loop | Task 5 |
| `_fetch_with_retries` dispatches on `proxy_session` | Task 5 |
| No-proxy path unchanged (429 retry preserved) | Task 5 (no change to no-proxy body) |
| `fetch_page` threads `proxy_session` | Task 6 |
| `run_agent` threads `proxy_session` | Task 6 |
| `execute()` creates one session per invocation | Task 6 |
| `_BROWSER_CFG` unchanged | Task 5 (no change) |
| Crawl4AI native fields left unset | Task 5 (not set in `_fetch_managed_proxy`) |
| All 22 spec tests | Tasks 1–6 |

**No placeholders found.** All steps include full code.

**Type consistency check:** `ManagedProxySession` defined in Task 2, imported in Tasks 5–6. `ProxyCredentials`, `ProxySettings` defined in Task 1, used consistently. `proxy_session: ManagedProxySession | None = None` used identically in all three signatures. `acquire_credentials` returns `tuple[ProxyCredentials | None, float]` in Task 2, destructured as `creds, wait` in Task 5 — consistent.
