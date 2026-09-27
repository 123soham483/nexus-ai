"""AgentFactory — shared registry mapping agent_type → agent class.

Single source of truth for which agent classes exist. Both the orchestrator
(default factory) and the Celery worker (injecting the real LLM provider and
shared memories) use it, so adding an agent is a one-line registry change
instead of editing two maps (previously duplicated in ``orchestrator.py`` and
``task_worker.py``).
"""
from __future__ import annotations

from typing import Dict, Optional, Type

from app.agents.base import BaseAgent
from app.agents.development.coder_agent import CoderAgent
from app.agents.development.debugger_agent import DebuggerAgent
from app.agents.development.optimizer_agent import OptimizerAgent
from app.agents.development.refactor_agent import RefactorAgent
from app.agents.quality.tester_agent import TesterAgent
from app.agents.quality.reviewer_agent import ReviewerAgent
from app.agents.quality.security_agent import SecurityAgent
from app.agents.knowledge.docs_agent import DocsAgent
from app.agents.knowledge.research_agent import ResearchAgent
from app.agents.knowledge.summarizer_agent import SummarizerAgent
from app.agents.coordination.planner_agent import PlannerAgent
from app.agents.coordination.validator_agent import ValidatorAgent
from app.agents.coordination.hallucination_detector import HallucinationDetector
from app.agents.coordination.cost_controller import CostController
from app.agents.coordination.hitl_controller import HitlController

#: Canonical agent registry — every implemented agent type maps to its class.
AGENT_CLASSES: Dict[str, Type[BaseAgent]] = {
    "coder": CoderAgent,
    "debugger": DebuggerAgent,
    "optimizer": OptimizerAgent,
    "refactor": RefactorAgent,
    "tester": TesterAgent,
    "reviewer": ReviewerAgent,
    "security": SecurityAgent,
    "docs": DocsAgent,
    "research": ResearchAgent,
    "summarizer": SummarizerAgent,
    "planner": PlannerAgent,
    "validator": ValidatorAgent,
    "hallucination_detector": HallucinationDetector,
    "cost_controller": CostController,
    "hitl_controller": HitlController,
}


class AgentFactory:
    """Creates agent instances by type, injecting shared providers.

    ``llm`` / ``short_term`` / ``long_term`` are passed to every created agent;
    leave them ``None`` for agents to fall back to their own defaults (e.g. the
    shared ``default_provider``). The registry is injectable (``agent_classes``
    and :meth:`register`) so tests can swap or add agent types.
    """

    def __init__(
        self,
        agent_classes: Optional[Dict[str, Type[BaseAgent]]] = None,
        llm=None,
        short_term=None,
        long_term=None,
    ) -> None:
        self._classes: Dict[str, Type[BaseAgent]] = (
            dict(agent_classes) if agent_classes is not None else dict(AGENT_CLASSES)
        )
        self.llm = llm
        self.short_term = short_term
        self.long_term = long_term

    def register(self, agent_type: str, cls: Type[BaseAgent]) -> None:
        """Add or replace the class for an agent type."""
        self._classes[agent_type] = cls

    def create(self, agent_type: str) -> BaseAgent:
        """Instantiate the agent for ``agent_type`` with the shared providers."""
        cls = self._classes.get(agent_type)
        if cls is None:
            raise ValueError(
                f"Unknown agent type: {agent_type!r}; known: {sorted(self._classes)}"
            )
        return cls(
            llm=self.llm,
            short_term=self.short_term,
            long_term=self.long_term,
        )


#: Shared default factory (no injected providers — agents use their own defaults).
default_factory = AgentFactory()
