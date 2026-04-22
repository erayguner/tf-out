"""Smoke tests for the ADK bridge.

The bridge is optional (``google-adk`` is a runtime dep), but when present it
must return a valid LlmAgent with a single working tool. This caught a prior
bug where ``sub_agents=[FunctionTool(...)]`` failed pydantic validation.
"""

from __future__ import annotations

import pytest

pytest.importorskip("google.adk")

from src.agents.adk_bridge import build_adk_root
from src.settings import load


def test_build_adk_root_returns_llm_agent_with_pipeline_tool():
    settings = load("config/settings.yaml")
    root = build_adk_root(settings)

    # LlmAgent, not SequentialAgent — the previous impl tried to stuff
    # FunctionTools into SequentialAgent.sub_agents and crashed.
    assert type(root).__name__ == "LlmAgent"
    assert root.name == "ai_tf_root"

    tool_names = [t.name for t in root.tools]
    assert tool_names == ["run_ai_tf_pipeline"]
