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
