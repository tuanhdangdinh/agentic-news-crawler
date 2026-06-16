"""Tests for deterministic extraction schema selection."""

from crawl_tool.engine.schema_registry import match_registered_schema


def test_match_registered_schema_for_key_financial_figures():
    match = match_registered_schema(
        "extract article title, publish date, stock tickers mentioned, and key financial figures"
    )

    assert match is not None
    name, schema = match
    figures = schema["properties"]["key_financial_figures"]

    assert name == "financial_article"
    assert figures["items"]["type"] == "object"
    assert figures["items"]["required"] == [
        "metric",
        "value",
        "entity",
        "period",
        "context",
    ]


def test_match_registered_schema_for_tickers_and_key_figures():
    match = match_registered_schema("Extract stock ticker symbols and key figures from the article")

    assert match is not None
    assert match[0] == "financial_article"


def test_match_registered_schema_ignores_unrelated_prompt():
    assert match_registered_schema("extract article title and author") is None


def test_match_registered_schema_ignores_non_financial_figures():
    assert match_registered_schema("extract non-financial figures about employee counts") is None
    assert match_registered_schema("extract non financial figures about employee counts") is None


def test_match_registered_schema_requires_complete_phrase():
    assert match_registered_schema("explain the financial figurehead mentioned") is None


def test_match_registered_schema_returns_independent_copy():
    first = match_registered_schema("extract key financial figures")
    second = match_registered_schema("extract key financial figures")

    assert first is not None
    assert second is not None
    first[1]["properties"]["article_title"]["description"] = "changed"

    assert second[1]["properties"]["article_title"]["description"] != "changed"
