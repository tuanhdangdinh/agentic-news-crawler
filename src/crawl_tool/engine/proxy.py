"""Job-scoped proxy session manager for username-encoded sticky sessions."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from urllib.parse import urlparse
from uuid import uuid4

import structlog
from crawl4ai import ProxyConfig, RoundRobinProxyStrategy

_log = structlog.get_logger(__name__)


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
    proxy_pool: tuple[ProxyCredentials, ...] = ()

    @classmethod
    def from_env(cls) -> ProxySettings:
        url = os.environ.get("PROXY_URL", "")
        proxy_pool = _load_proxy_pool()
        username_template = os.environ.get("PROXY_USERNAME_TEMPLATE", "user-session-{session_id}")
        if url and not proxy_pool and "{session_id}" not in username_template:
            raise ValueError("PROXY_USERNAME_TEMPLATE must include {session_id} for rotation")
        return cls(
            enabled=bool(url or proxy_pool),
            url=url,
            username_template=username_template,
            password=os.environ.get("PROXY_PASSWORD", ""),
            rotate_after_requests=int(os.environ.get("PROXY_ROTATE_AFTER_REQUESTS", "20")),
            domain_delay=float(os.environ.get("PROXY_DOMAIN_DELAY_SECONDS", "2")),
            block_backoff=float(os.environ.get("PROXY_BLOCK_BACKOFF_SECONDS", "30")),
            proxy_pool=proxy_pool,
        )

    def __repr__(self) -> str:
        return (
            f"ProxySettings(enabled={self.enabled!r}, url={self.url!r}, "
            f"username_template={self.username_template!r}, password='***', "
            f"rotate_after_requests={self.rotate_after_requests!r}, "
            f"domain_delay={self.domain_delay!r}, block_backoff={self.block_backoff!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


def _load_proxy_pool() -> tuple[ProxyCredentials, ...]:
    path = os.environ.get("PROXY_LIST_FILE") or os.environ.get("WEBSHARE_PROXY_LIST_FILE")
    if not path:
        return ()
    return tuple(
        _proxy_credentials_from_line(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _proxy_credentials_from_line(line: str) -> ProxyCredentials:
    text = line.strip()
    if "@" in text:
        parsed = urlparse(text if "://" in text else f"http://{text}")
        return ProxyCredentials(
            server=f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
            username=parsed.username or "",
            password=parsed.password or "",
        )

    fields = text.split(":")
    if len(fields) == 4:
        host, port, username, password = fields
        return ProxyCredentials(
            server=f"http://{host}:{port}",
            username=username,
            password=password,
        )
    if len(fields) == 2:
        host, port = fields
        return ProxyCredentials(server=f"http://{host}:{port}", username="", password="")
    raise ValueError("unsupported proxy list line format")


@dataclass
class _DomainSession:
    session_id: str
    request_count: int
    last_request_at: float


class ManagedProxySession:
    """Job-scoped sticky proxy session manager keyed on normalised domain.

    Pool-backend rotation (when ``settings.proxy_pool`` is set) delegates to
    Crawl4AI's ``RoundRobinProxyStrategy``, using the domain as the strategy's
    session_id. Domain pacing, the request-count rotation threshold, and the
    managed-provider username-templating backend have no native equivalent and
    stay implemented here.
    """

    def __init__(self, settings: ProxySettings) -> None:
        self._settings = settings
        self._sessions: dict[str, _DomainSession] = {}
        self._lock = asyncio.Lock()
        self._pool_strategy: RoundRobinProxyStrategy | None = None
        if settings.proxy_pool:
            self._pool_strategy = RoundRobinProxyStrategy(
                [
                    ProxyConfig(server=c.server, username=c.username, password=c.password)
                    for c in settings.proxy_pool
                ]
            )

    @property
    def settings(self) -> ProxySettings:
        return self._settings

    async def acquire_credentials(self, domain: str) -> tuple[ProxyCredentials | None, float]:
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
                    await self._rotate_unlocked(domain, reason="threshold")
                    ds = self._sessions[domain]

            ds.request_count += 1
            ds.last_request_at = monotonic()

            if self._pool_strategy is not None:
                pool_proxy = await self._pool_strategy.get_proxy_for_session(domain)
                return (
                    ProxyCredentials(
                        server=pool_proxy.server,
                        username=pool_proxy.username or "",
                        password=pool_proxy.password or "",
                    ),
                    wait,
                )

            username = self._settings.username_template.format(session_id=ds.session_id)
            return (
                ProxyCredentials(
                    server=self._settings.url,
                    username=username,
                    password=self._settings.password,
                ),
                wait,
            )

    async def _rotate_unlocked(self, domain: str, reason: str) -> None:
        """Replace the current domain session. Caller must hold _lock."""
        old = self._sessions.get(domain)
        old_count = old.request_count if old else 0
        old_prefix = old.session_id[:8] if old else "none"
        if self._pool_strategy is not None:
            await self._pool_strategy.release_session(domain)
        new_session = _DomainSession(session_id=uuid4().hex, request_count=0, last_request_at=0.0)
        self._sessions[domain] = new_session
        _log.info(
            "proxy session rotated",
            domain=domain,
            reason=reason,
            old_session_prefix=old_prefix,
            new_session_prefix=new_session.session_id[:8],
            requests_on_old=old_count,
        )

    async def rotate(self, domain: str, *, reason: str) -> None:
        """Retire the current session for domain. Next acquire_credentials creates a new one."""
        async with self._lock:
            await self._rotate_unlocked(domain, reason=reason)
