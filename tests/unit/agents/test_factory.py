"""Unit tests for the shared AgentFactory registry (Phase 2)."""
from __future__ import annotations

import pytest

from app.agents.base import BaseAgent
from app.agents.development.coder_agent import CoderAgent
from app.agents.factory import AGENT_CLASSES, AgentFactory, default_factory


class FakeLLM:
    pass


class _StubAgent(BaseAgent):
    agent_type = "stub"


def test_default_factory_creates_matching_agent():
    agent = default_factory.create("coder")
    assert isinstance(agent, CoderAgent)
    assert agent.agent_type == "coder"


def test_every_registered_agent_type_creates():
    for agent_type, cls in AGENT_CLASSES.items():
        agent = default_factory.create(agent_type)
        assert isinstance(agent, cls)
        assert agent.agent_type == agent_type


def test_unknown_agent_type_raises():
    with pytest.raises(ValueError, match="Unknown agent type"):
        default_factory.create("does-not-exist")


def test_injected_providers_passed_to_created_agent():
    llm = FakeLLM()
    short_term = object()
    long_term = object()
    factory = AgentFactory(llm=llm, short_term=short_term, long_term=long_term)
    agent = factory.create("coder")
    assert agent.llm is llm
    assert agent.short_term is short_term
    assert agent.long_term is long_term


def test_register_adds_new_agent_type():
    factory = AgentFactory()
    factory.register("stub", _StubAgent)
    agent = factory.create("stub")
    assert isinstance(agent, _StubAgent)
    assert agent.agent_type == "stub"


def test_custom_registry_overrides_default_classes():
    factory = AgentFactory(agent_classes={"coder": _StubAgent})
    assert isinstance(factory.create("coder"), _StubAgent)
    # The injected registry replaces (not merges with) the default one.
    with pytest.raises(ValueError, match="Unknown agent type"):
        factory.create("tester")


def test_factory_create_is_callable_factory_function():
    # _build_agent_factory returns AgentFactory.create — verify the bound method
    # works as a plain callable (what the orchestrator receives).
    factory = AgentFactory(llm=FakeLLM())
    create = factory.create
    agent = create("coder")
    assert agent.agent_type == "coder"
    assert agent.llm is factory.llm
