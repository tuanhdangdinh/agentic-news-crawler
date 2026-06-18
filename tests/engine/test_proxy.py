"""Unit tests for crawl_engine.proxy."""

from __future__ import annotations

import pytest

from crawl_tool.engine.proxy import ManagedProxySession, ProxyCredentials, ProxySettings


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
    assert settings.password == "secret"
    assert settings.username_template == "user-session-{session_id}"
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


def test_proxy_settings_repr_omits_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY_URL", "http://proxy.example.com:8080")
    monkeypatch.setenv("PROXY_PASSWORD", "topsecret")
    settings = ProxySettings.from_env()
    assert "topsecret" not in repr(settings)
    assert "topsecret" not in str(settings)


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
    import asyncio

    session = ManagedProxySession(proxy_settings)
    results = await asyncio.gather(*[session.acquire_credentials("example.com") for _ in range(5)])
    usernames = [r[0].username for r in results if r[0] is not None]
    assert len(usernames) == 5
    assert len(set(usernames)) == 1  # all share the same initial session
