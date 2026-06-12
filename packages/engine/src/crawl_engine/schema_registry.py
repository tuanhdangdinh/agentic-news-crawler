"""Deterministic JSON Schema selection for known extraction intents."""

from __future__ import annotations

import re
from copy import deepcopy

_FINANCIAL_FIGURE_PHRASES = (
    "financial figure",
    "financial figures",
    "financial metric",
    "financial metrics",
    "key financial figure",
    "key financial figures",
    "key financial metric",
    "key financial metrics",
)
_KEY_FIGURE_PHRASES = ("key figure", "key figures", "key metric", "key metrics")
_STOCK_TICKER_PHRASES = ("stock ticker", "stock tickers", "ticker symbol", "ticker symbols")

_FINANCIAL_ARTICLE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "article_title": {
            "type": ["string", "null"],
            "description": "Article headline exactly as published, or null when unavailable.",
        },
        "publish_date": {
            "type": ["string", "null"],
            "description": "Article publication date in ISO 8601 format, or null when unavailable.",
        },
        "stock_tickers": {
            "type": ["array", "null"],
            "description": (
                "Explicit company stock ticker symbols mentioned in the article. "
                "Exclude market index names, exchange names, and inferred symbols."
            ),
            "items": {"type": "string"},
        },
        "key_financial_figures": {
            "type": ["array", "null"],
            "description": (
                "Material financial figures that can be tied to a named metric and entity. "
                "Exclude dates, counts, percentages, and bare numbers without financial meaning."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "description": "Named financial metric, such as revenue, profit, or EPS.",
                    },
                    "value": {
                        "type": "string",
                        "description": (
                            "Reported value with its currency, unit, magnitude, or percentage."
                        ),
                    },
                    "entity": {
                        "type": "string",
                        "description": "Company, organization, asset, or market the figure describes.",
                    },
                    "period": {
                        "type": ["string", "null"],
                        "description": "Reporting period or comparison period, or null if unstated.",
                    },
                    "context": {
                        "type": "string",
                        "description": (
                            "Short evidence phrase explaining what the figure means in the article."
                        ),
                    },
                },
                "required": ["metric", "value", "entity", "period", "context"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["article_title", "publish_date", "stock_tickers", "key_financial_figures"],
    "additionalProperties": False,
}


def _normalize(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt.casefold()).strip()


def _contains_any(prompt: str, phrases: tuple[str, ...]) -> bool:
    return any(
        re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", prompt) for phrase in phrases
    )


def _contains_financial_figure_phrase(prompt: str) -> bool:
    for phrase in _FINANCIAL_FIGURE_PHRASES:
        pattern = rf"(?<![\w-]){re.escape(phrase)}(?![\w-])"
        for match in re.finditer(pattern, prompt):
            preceding_words = prompt[: match.start()].split()
            if not preceding_words or preceding_words[-1] != "non":
                return True
    return False


def match_registered_schema(prompt: str) -> tuple[str, dict] | None:
    """Return a named schema for a recognized extraction intent.

    Args:
        prompt: Natural-language extraction request.

    Returns:
        Schema name and an independent schema copy, or None when no intent matches.
    """
    normalized = _normalize(prompt)
    financial_figures = _contains_financial_figure_phrase(normalized)
    ticker_key_figures = _contains_any(normalized, _STOCK_TICKER_PHRASES) and _contains_any(
        normalized, _KEY_FIGURE_PHRASES
    )
    if financial_figures or ticker_key_figures:
        return "financial_article", deepcopy(_FINANCIAL_ARTICLE_SCHEMA)
    return None
