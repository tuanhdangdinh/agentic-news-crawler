"""Tests for engine/storage.py."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from crawl_tool.engine.storage import (
    StorageSettings,
    _delete_result_sync,
    _get_result_sync,
    _list_results_sync,
    _put_result_sync,
)


def _settings() -> StorageSettings:
    return StorageSettings(
        endpoint="localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        bucket="crawl-results",
        secure=False,
    )


def test_storage_settings_disabled_when_no_endpoint():
    s = StorageSettings(endpoint="", access_key="", secret_key="", bucket="b", secure=False)
    assert not s.enabled


def test_storage_settings_enabled_when_endpoint_set():
    assert _settings().enabled


def test_storage_settings_from_env(monkeypatch):
    monkeypatch.setenv("MINIO_ENDPOINT", "myhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "key")
    monkeypatch.setenv("MINIO_SECRET_KEY", "secret")
    monkeypatch.setenv("MINIO_BUCKET", "mybucket")
    monkeypatch.setenv("MINIO_SECURE", "true")
    s = StorageSettings.from_env()
    assert s.endpoint == "myhost:9000"
    assert s.bucket == "mybucket"
    assert s.secure is True


def test_put_result_injects_job_id_into_meta():
    """put_result must inject job_id into the stored meta without mutating original payload."""
    uploaded: dict = {}

    mock_client = MagicMock()
    mock_client.bucket_exists.return_value = True

    def capture_put(bucket_name, object_name, data, length, content_type):
        uploaded["body"] = json.loads(data.read())

    mock_client.put_object.side_effect = capture_put

    payload = {"meta": {"seed_url": "https://example.com", "total_pages": 1}, "pages": []}

    with patch("crawl_tool.engine.storage._make_client", return_value=mock_client):
        _put_result_sync("abc123", payload, _settings())

    assert uploaded["body"]["meta"]["job_id"] == "abc123"
    assert uploaded["body"]["meta"]["seed_url"] == "https://example.com"
    # original payload is not mutated
    assert "job_id" not in payload["meta"]


def test_put_result_creates_bucket_if_missing():
    mock_client = MagicMock()
    mock_client.bucket_exists.return_value = False

    with patch("crawl_tool.engine.storage._make_client", return_value=mock_client):
        _put_result_sync("xyz", {"meta": {}, "pages": []}, _settings())

    mock_client.make_bucket.assert_called_once_with("crawl-results")


def test_get_result_returns_bytes_on_success():
    mock_response = MagicMock()
    mock_response.read.return_value = b'{"meta": {}}'
    mock_client = MagicMock()
    mock_client.get_object.return_value = mock_response

    with patch("crawl_tool.engine.storage._make_client", return_value=mock_client):
        result = _get_result_sync("abc123", _settings())

    assert result == b'{"meta": {}}'
    mock_response.close.assert_called_once()


def test_get_result_returns_none_on_missing_key():
    from minio.error import S3Error

    mock_client = MagicMock()
    err = S3Error(
        code="NoSuchKey",
        message="not found",
        resource="url",
        request_id="req",
        host_id="host",
        response=MagicMock(),
    )
    mock_client.get_object.side_effect = err

    with patch("crawl_tool.engine.storage._make_client", return_value=mock_client):
        result = _get_result_sync("missing", _settings())

    assert result is None


def test_list_results_returns_objects():
    mock_obj = MagicMock()
    mock_obj.object_name = "crawl-abc123.json"
    mock_obj.size = 1024
    mock_obj.last_modified = datetime(2026, 6, 29, 10, 0, 0, tzinfo=UTC)

    mock_client = MagicMock()
    mock_client.list_objects.return_value = [mock_obj]

    with patch("crawl_tool.engine.storage._make_client", return_value=mock_client):
        results = _list_results_sync(_settings())

    assert results == [
        {"job_id": "abc123", "size_bytes": 1024, "last_modified": "2026-06-29T10:00:00+00:00"}
    ]
    mock_client.list_objects.assert_called_once_with("crawl-results")


def test_list_results_empty_bucket():
    mock_client = MagicMock()
    mock_client.list_objects.return_value = []

    with patch("crawl_tool.engine.storage._make_client", return_value=mock_client):
        results = _list_results_sync(_settings())

    assert results == []


def test_delete_result_calls_remove_object():
    mock_client = MagicMock()

    with patch("crawl_tool.engine.storage._make_client", return_value=mock_client):
        _delete_result_sync("abc123", _settings())

    mock_client.remove_object.assert_called_once_with("crawl-results", "crawl-abc123.json")
