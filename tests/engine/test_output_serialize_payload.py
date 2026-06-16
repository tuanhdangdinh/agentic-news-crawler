"""Tests for crawl_engine.output.serialize_payload."""

from __future__ import annotations

import json

from crawl_tool.engine.output import serialize_payload

_PAYLOAD = {
    "meta": {"total_pages": 2},
    "pages": [{"url": "https://a", "title": "A"}, {"url": "https://b", "title": "B"}],
}


def test_serialize_json_round_trips_full_payload():
    text = serialize_payload(_PAYLOAD, "json")
    assert json.loads(text) == _PAYLOAD


def test_serialize_jsonl_is_one_object_per_page():
    text = serialize_payload(_PAYLOAD, "jsonl")
    lines = text.splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["url"] == "https://a"
    assert json.loads(lines[1])["url"] == "https://b"


def test_serialize_defaults_to_json():
    assert json.loads(serialize_payload(_PAYLOAD))["meta"]["total_pages"] == 2


def test_serialize_jsonl_handles_no_pages():
    assert serialize_payload({"meta": {}, "pages": []}, "jsonl") == ""
