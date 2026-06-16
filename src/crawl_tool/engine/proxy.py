"""Job-scoped proxy session manager for username-encoded sticky sessions."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4

import structlog

_log = structlog.get_logger(__name__)


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

    def __repr__(self) -> str:
        return (
            f"ProxySettings(enabled={self.enabled!r}, url={self.url!r}, "
            f"username_template={self.username_template!r}, password='***', "
            f"rotate_after_requests={self.rotate_after_requests!r}, "
            f"domain_delay={self.domain_delay!r}, block_backoff={self.block_backoff!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


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
        old = self._sessions.get(domain)
        old_count = old.request_count if old else 0
        old_prefix = old.session_id[:8] if old else "none"
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
            self._rotate_unlocked(domain, reason=reason)
