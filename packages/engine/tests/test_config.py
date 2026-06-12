"""Tests for crawl_engine.config."""

from __future__ import annotations

import pytest
from crawl_engine.config import MAX_DEPTH_CEILING, MODEL, AgentConfig
from pydantic import ValidationError


def test_default_max_depth_is_one():
    assert AgentConfig().max_depth == 1


def test_max_depth_ceiling_is_five():
    assert MAX_DEPTH_CEILING == 5
    assert AgentConfig(max_depth=5).max_depth == 5


def test_max_depth_above_ceiling_rejected():
    with pytest.raises(ValidationError):
        AgentConfig(max_depth=6)


def test_agent_module_reexports_config():
    from crawl_engine.agent import (
        MAX_DEPTH_CEILING as MaxDepthCeilingViaAgent,
    )
    from crawl_engine.agent import MODEL as ModelViaAgent
    from crawl_engine.agent import AgentConfig as AgentConfigViaAgent

    assert AgentConfigViaAgent is AgentConfig
    assert ModelViaAgent is MODEL
    assert MaxDepthCeilingViaAgent is MAX_DEPTH_CEILING
