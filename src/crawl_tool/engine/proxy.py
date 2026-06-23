"""Job-scoped proxy credential rotator."""

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

logger = structlog.get_logger(__name__)


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
            domain_delay=float(os.environ.get("PROXY_DOMAIN_DELAY_SECONDS", "2")),
            block_backoff=float(os.environ.get("PROXY_BLOCK_BACKOFF_SECONDS", "30")),
            proxy_pool=proxy_pool,
        )

    def __repr__(self) -> str:
        return (
            f"ProxySettings(enabled={self.enabled!r}, url={self.url!r}, "
            f"username_template={self.username_template!r}, password='***', "
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


class ProxyRotator:
    """Job-scoped proxy credential rotator keyed on normalised domain.

    Pool-backend rotation (when ``settings.proxy_pool`` is set) delegates to
    Crawl4AI's ``RoundRobinProxyStrategy.get_next_proxy()`` — a single shared
    cycle across the whole job, not scoped per domain. Domain pacing and
    managed-provider username templating have no native equivalent and stay
    implemented here.
    """

    def __init__(self, settings: ProxySettings) -> None:
        self._settings = settings
        self._last_request_at: dict[str, float] = {}
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

    async def next_credentials(self, domain: str) -> tuple[ProxyCredentials | None, float]:
        """Issue the next proxy credentials for a domain.

        Args:
            domain: Normalized domain used for per-domain pacing. Pool rotation
                itself is a single shared cycle across the whole job.

        Returns:
            Credentials and seconds to wait before use. Credentials are None when
            proxy routing is disabled.
        """
        if not self._settings.enabled:
            return None, 0.0

        async with self._lock:
            now = monotonic()
            last_request_at = self._last_request_at.get(domain)

            if last_request_at is None:
                wait = 0.0
            else:
                # Keep per-domain pacing even though credentials rotate on every request.
                wait = max(0.0, self._settings.domain_delay - (now - last_request_at))

            if self._pool_strategy is not None:
                pool_proxy = await self._pool_strategy.get_next_proxy()
                self._last_request_at[domain] = monotonic()
                logger.debug(
                    "proxy credentials issued",
                    domain=domain,
                    backend="pool",
                    server=pool_proxy.server,
                    wait=round(wait, 2),
                )
                return (
                    ProxyCredentials(
                        server=pool_proxy.server,
                        username=pool_proxy.username or "",
                        password=pool_proxy.password or "",
                    ),
                    wait,
                )

            # Templated providers rotate by embedding a fresh session id in the username.
            self._last_request_at[domain] = monotonic()
            username = self._settings.username_template.format(session_id=uuid4().hex)
            logger.debug(
                "proxy credentials issued",
                domain=domain,
                backend="templated",
                wait=round(wait, 2),
            )
            return (
                ProxyCredentials(
                    server=self._settings.url,
                    username=username,
                    password=self._settings.password,
                ),
                wait,
            )
