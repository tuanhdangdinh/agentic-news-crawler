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
