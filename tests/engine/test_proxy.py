"""Unit tests for crawl_engine.proxy."""

from __future__ import annotations

import pytest

from crawl_tool.engine.proxy import ProxyCredentials, ProxyRotator, ProxySettings


def test_proxy_settings_disabled_when_url_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROXY_URL", raising=False)
    monkeypatch.delenv("PROXY_LIST_FILE", raising=False)
    monkeypatch.delenv("WEBSHARE_PROXY_LIST_FILE", raising=False)
    settings = ProxySettings.from_env()
    assert settings.enabled is False


def test_proxy_settings_enabled_when_url_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY_URL", "http://proxy.example.com:8080")
    monkeypatch.setenv("PROXY_PASSWORD", "secret")
    monkeypatch.delenv("PROXY_USERNAME_TEMPLATE", raising=False)
    monkeypatch.delenv("PROXY_DOMAIN_DELAY_SECONDS", raising=False)
    monkeypatch.delenv("PROXY_BLOCK_BACKOFF_SECONDS", raising=False)
    settings = ProxySettings.from_env()
    assert settings.enabled is True
    assert settings.url == "http://proxy.example.com:8080"
    assert settings.password == "secret"
    assert settings.username_template == "user-session-{session_id}"
    assert settings.domain_delay == 2.0
    assert settings.block_backoff == 30.0


def test_proxy_settings_rejects_static_username_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROXY_URL", "http://proxy.example.com:8080")
    monkeypatch.setenv("PROXY_USERNAME_TEMPLATE", "static-user")
    with pytest.raises(ValueError, match="PROXY_USERNAME_TEMPLATE"):
        ProxySettings.from_env()


def test_proxy_settings_loads_webshare_proxy_list_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text(
        "31.59.20.176:6754:user1:pass1\n92.113.242.158:6742:user2:pass2\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("PROXY_URL", raising=False)
    monkeypatch.setenv("PROXY_LIST_FILE", str(proxy_file))

    settings = ProxySettings.from_env()

    assert settings.enabled is True
    assert len(settings.proxy_pool) == 2
    assert settings.proxy_pool[0] == ProxyCredentials(
        server="http://31.59.20.176:6754", username="user1", password="pass1"
    )


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
    monkeypatch.delenv("PROXY_USERNAME_TEMPLATE", raising=False)
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
        domain_delay=2.0,
        block_backoff=30.0,
    )


async def test_next_credentials_disabled_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROXY_URL", raising=False)
    settings = ProxySettings.from_env()
    rotator = ProxyRotator(settings)
    creds, wait = await rotator.next_credentials("example.com")
    assert creds is None
    assert wait == 0.0


async def test_next_credentials_first_visit(proxy_settings: ProxySettings) -> None:
    rotator = ProxyRotator(proxy_settings)
    creds, wait = await rotator.next_credentials("example.com")
    assert isinstance(creds, ProxyCredentials)
    assert wait == 0.0
    assert creds.server == "http://proxy.example.com:8080"
    assert creds.username.startswith("user-session-")
    assert len(creds.username.split("-")[-1]) == 32  # UUID4 hex suffix


async def test_next_credentials_rotates_same_domain(proxy_settings: ProxySettings) -> None:
    rotator = ProxyRotator(proxy_settings)
    creds1, _ = await rotator.next_credentials("example.com")
    creds2, _ = await rotator.next_credentials("example.com")
    assert creds1 is not None and creds2 is not None
    assert creds1.username != creds2.username


async def test_next_credentials_separate_domains_get_distinct_credentials(
    proxy_settings: ProxySettings,
) -> None:
    rotator = ProxyRotator(proxy_settings)
    creds_a, _ = await rotator.next_credentials("site-a.com")
    creds_b, _ = await rotator.next_credentials("site-b.com")
    assert creds_a is not None and creds_b is not None
    assert creds_a.username != creds_b.username


async def test_next_credentials_domain_delay(proxy_settings: ProxySettings) -> None:
    rotator = ProxyRotator(proxy_settings)
    _, wait1 = await rotator.next_credentials("example.com")
    _, wait2 = await rotator.next_credentials("example.com")
    assert wait1 == 0.0
    assert wait2 > 0.0


async def test_next_credentials_advances_proxy_pool_entry() -> None:
    settings = ProxySettings(
        enabled=True,
        url="",
        username_template="",
        password="",
        domain_delay=0.0,
        block_backoff=0.0,
        proxy_pool=(
            ProxyCredentials(server="http://proxy-a:8080", username="user-a", password="pass-a"),
            ProxyCredentials(server="http://proxy-b:8080", username="user-b", password="pass-b"),
        ),
    )
    rotator = ProxyRotator(settings)

    creds_before, _ = await rotator.next_credentials("example.com")
    creds_after, _ = await rotator.next_credentials("example.com")

    assert creds_before is not None and creds_after is not None
    assert creds_before.server == "http://proxy-a:8080"
    assert creds_after.server == "http://proxy-b:8080"


async def test_next_credentials_wraps_around_proxy_pool() -> None:
    settings = ProxySettings(
        enabled=True,
        url="",
        username_template="",
        password="",
        domain_delay=0.0,
        block_backoff=0.0,
        proxy_pool=(
            ProxyCredentials(server="http://proxy-a:8080", username="user-a", password="pass-a"),
            ProxyCredentials(server="http://proxy-b:8080", username="user-b", password="pass-b"),
        ),
    )
    rotator = ProxyRotator(settings)

    servers = []
    for _ in range(3):
        creds, _ = await rotator.next_credentials("example.com")
        assert creds is not None
        servers.append(creds.server)

    assert servers == [
        "http://proxy-a:8080",
        "http://proxy-b:8080",
        "http://proxy-a:8080",
    ]


async def test_concurrent_next_credentials_rotates_each_request(
    proxy_settings: ProxySettings,
) -> None:
    import asyncio

    rotator = ProxyRotator(proxy_settings)
    results = await asyncio.gather(*[rotator.next_credentials("example.com") for _ in range(5)])
    usernames = [r[0].username for r in results if r[0] is not None]
    assert len(usernames) == 5
    assert len(set(usernames)) == 5
