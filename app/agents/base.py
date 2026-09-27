"""BaseAgent — the abstract agent every concrete agent subclasses.

A single ``run`` defines the agent lifecycle shared by all 15 agents:

    1. load recent conversation from short-term memory (Redis)
    2. retrieve semantically-relevant memories from long-term memory (Chroma)
    3. build the system + user prompts (overridable hooks)
    4. call the LLM via ``LLMProvider.complete`` (with provider fallback)
    5. parse the response (overridable) and store it back to memory
    6. return an ``AgentResult`` that trivially converts to an ``AgentRun`` row

Memories and the LLM provider are injected, so unit tests drive the whole
lifecycle with fakes — no Redis, Chroma, network, or DB required. Persistence of
the ``AgentRun`` is left to the orchestrator (Step 1.11); the agent only *builds*
the row via :meth:`AgentResult.to_agent_run`.
"""
from __future__ import annotations

import json
import time
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.llm import CompletionResult, LLMMessage, LLMProvider, default_provider
from app.observability.metrics import record_agent_run
from app.observability.tracer import (
    AGENT_CONFIDENCE,
    NexusTracer,
    get_tracer,
)


@dataclass
class AgentResult:
    """Everything one agent invocation produced, ready to persist or return."""

    agent_type: str
    agent_id: str
    provider: str
    model: str
    system_prompt: str
    user_prompt: str
    content: str  # raw LLM text
    parsed: Any  # output of parse_response
    reasoning: Optional[str] = None
    tools_called: List[Any] = field(default_factory=list)
    memory_retrieved: List[Any] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    status: str = "completed"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    success: bool = True
    error: Optional[str] = None
    task_id: Optional[Any] = None
    confidence_score: float = 1.0
    fallback_used: bool = False
    model_used: Optional[str] = None

    @property
    def output(self) -> Any:
        return self.parsed

    def to_agent_run(self, task_id):
        """Build (unsaved) an ``AgentRun`` ORM row from this result."""
        from app.db.models.agent_run import AgentRun

        return AgentRun(
            task_id=task_id,
            agent_type=self.agent_type,
            agent_id=self.agent_id,
            llm_provider=self.provider,
            llm_model=self.model,
            status=self.status,
            system_prompt=self.system_prompt,
            user_prompt=self.user_prompt,
            llm_response=self.content,
            reasoning=self.reasoning,
            tools_called=list(self.tools_called),
            memory_retrieved=list(self.memory_retrieved),
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cost_usd=self.cost_usd,
            started_at=self.started_at,
            completed_at=self.completed_at,
            duration_seconds=self.duration_seconds,
        )


class BaseAgent:
    """Abstract base for all agents. Subclasses set ``agent_type`` +
    ``system_prompt`` (or override the hooks) and usually ``parse_response``."""

    #: short identifier; also the key into ``AGENT_LLM_MAP`` for provider routing.
    agent_type: str = "base"
    #: default system prompt; override ``build_system_prompt`` for dynamic prompts.
    system_prompt: str = "You are a helpful AI agent."
    #: how many long-term memories to retrieve per run.
    memory_top_k: int = 5

    def __init__(        self, llm: Optional[LLMProvider] = None,
        short_term=None,
        long_term=None,
        *,
        agent_id: Optional[str] = None,
        provider: Optional[str] = None,
        tracer: Optional[NexusTracer] = None,
    ) -> None:
        self.llm = llm or default_provider
        #: Phase 4 distributed tracing. The shared tracer is a no-op unless
        #: OpenTelemetry is installed and ENABLE_OPENTELEMETRY is on, so agents
        #: need no branching around it.
        self.tracer = tracer if tracer is not None else get_tracer()
        self.short_term = short_term  # ShortTermMemory | None (duck-typed)
        self.long_term = long_term  # LongTermMemory | None (duck-typed)
        self.agent_id = agent_id or _uuid.uuid4().hex[:12]
        # Explicit provider override; otherwise routing uses ``agent_type``.
        self.provider_override = provider

    # ── overridable hooks ────────────────────────────────────────────────────
    def build_system_prompt(self, context: Dict[str, Any]) -> str:
        """Return the system prompt. Default: the class ``system_prompt``."""
        return self.system_prompt

    def build_user_prompt(
        self, goal: str, context: Dict[str, Any], memories: List[str]
    ) -> str:
        """Compose the user turn from the goal, structured context, and memories."""
        parts: List[str] = []
        if memories:
            parts.append(
                "Relevant memory from past work:\n"
                + "\n".join(f"- {m}" for m in memories)
            )
        if context:
            parts.append("Context:\n" + json.dumps(context, default=str, indent=2))
        parts.append(f"Task:\n{goal}")
        return "\n\n".join(parts)

    def parse_response(self, content: str) -> Any:
        """Turn raw LLM text into a structured result. Default: stripped text."""
        return content.strip()

    async def post_process(
        self, parsed: Any, context: Dict[str, Any], task_id
    ) -> Any:
        """Optional hook to validate/replace the parsed output (default: identity).

        Runs between ``parse_response`` and ``_calculate_confidence`` so an agent
        can act on what it just produced — the TesterAgent executes the tests it
        wrote in the sandbox and folds the real result in (Phase 3, Step 3.6).
        Implementations must never raise: degrade to ``parsed`` unchanged.
        """
        return parsed

    # ── memory helpers ───────────────────────────────────────────────────────
    async def _load_history(self, task_id) -> List[Dict[str, str]]:
        """Recent conversation messages for this task from short-term memory."""
        if self.short_term is not None and task_id is not None:
            return list(await self.short_term.get_messages(task_id))
        return []

    async def _search_memory(self, query: str) -> List[str]:
        """Documents of the top-k relevant long-term memories (as plain strings)."""
        if self.long_term is None or not query:
            return []
        hits = await self.long_term.search(query, n_results=self.memory_top_k)
        docs: List[str] = []
        for h in hits:
            docs.append(getattr(h, "document", None) or str(h))
        return docs

    async def _store_turn(self, task_id, user_prompt: str, response: str) -> None:
        """Append this turn to short-term memory for later runs on the same task."""
        if self.short_term is None or task_id is None:
            return
        await self.short_term.add_message(task_id, "user", user_prompt)
        await self.short_term.add_message(task_id, "assistant", response)

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def run(
        self,
        goal: str,
        *,
        task_id=None,
        context: Optional[Dict[str, Any]] = None,
        memory_query: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        store: bool = True,
    ) -> AgentResult:
        """Execute one full agent turn and return a structured result."""
        context = context or {}
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        history = await self._load_history(task_id)
        memories = await self._search_memory(memory_query or goal)

        system_prompt = self.build_system_prompt(context)
        user_prompt = self.build_user_prompt(goal, context, memories)

        messages: List[LLMMessage] = [LLMMessage("system", system_prompt)]
        for m in history:
            messages.append(LLMMessage(m.get("role", "user"), m.get("content", "")))
        messages.append(LLMMessage("user", user_prompt))

        completion: CompletionResult = await self.llm.complete(
            messages,
            provider=self.provider_override,
            agent_type=self.agent_type,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        if store:
            await self._store_turn(task_id, user_prompt, completion.content)

        completed_at = datetime.now(timezone.utc)
        return AgentResult(
            agent_type=self.agent_type,
            agent_id=self.agent_id,
            provider=completion.provider,
            model=completion.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            content=completion.content,
            parsed=self.parse_response(completion.content),
            memory_retrieved=memories,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            cost_usd=completion.cost_usd,
            status="completed",
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=time.perf_counter() - t0,
        )

    # ── full lifecycle with confidence + long-term storage (execute) ────────
    #: Confidence above which :meth:`execute` stores the result in long-term
    #: memory for future reuse. Agents may override.
    _store_confidence_threshold: float = 0.8
    #: Temperature for the LLM call made by :meth:`execute`. Agents override for
    #: determinism (e.g. security/validator use 0.0) or consistency (coder 0.1).
    temperature: float = 0.7
    #: Keys checked (in order) when extracting the ``reasoning`` field.
    _reasoning_keys: Tuple[str, ...] = (
        "reasoning", "root_cause", "assessment", "analysis",
    )
    #: Keys checked (in order) when building the long-term-memory summary.
    _summary_keys: Tuple[str, ...] = (
        "code", "fix", "explanation", "verification", "results", "summary",
    )

    @staticmethod
    def _goal_from_task(task) -> str:
        """Coerce a task argument (str, dict with ``goal``, or Task object) to a string."""
        if isinstance(task, str):
            return task
        if isinstance(task, dict):
            return str(task.get("goal", task))
        return str(getattr(task, "goal", task))

    async def _retrieve_memory(self, goal: str) -> List[str]:
        """Relevant long-term-memory docs for this goal, as plain strings.

        Degrades to an empty result if the memory backend is unavailable
        (e.g. optional vector-store dependencies not installed) so that a
        memory outage never fails agent execution.
        """
        if self.long_term is None or not goal:
            return []
        search_fn = getattr(self.long_term, "search_similar_tasks", None)
        try:
            if search_fn is not None:
                hits = await search_fn(goal, n_results=self.memory_top_k)
            else:
                hits = await self.long_term.search(goal, n_results=self.memory_top_k)
        except Exception as exc:  # pragma: no cover - depends on optional deps
            import logging
            logging.getLogger(__name__).warning(
                "long-term memory search degraded to empty: %s", exc
            )
            return []
        docs: List[str] = []
        for h in hits:
            doc = getattr(h, "content", None) or getattr(h, "document", None) or str(h)
            docs.append(doc)
        return docs

    def _calculate_confidence(self, parsed: Any) -> float:
        """Default confidence heuristic. Agents override with domain scoring."""
        if not parsed:
            return 0.0
        if isinstance(parsed, dict):
            if not any(parsed.values()):
                return 0.0
            if any(isinstance(v, str) and len(v) > 50 for v in parsed.values()):
                return 0.9
            return 0.6
        text = str(parsed).strip()
        return 0.8 if len(text) > 50 else 0.4

    def _memory_summary(self, parsed: Any, content: str) -> str:
        """What gets stored as the long-term-memory summary for this agent."""
        if isinstance(parsed, dict):
            for key in self._summary_keys:
                value = parsed.get(key)
                if value:
                    return str(value)
        return content

    async def _store_success_memory(
        self, goal: str, parsed: Any, completion: CompletionResult,
        confidence: float, task_id,
    ) -> None:
        """Persist a high-confidence result to long-term memory for future reuse."""
        if self.long_term is None:
            return
        store_fn = getattr(self.long_term, "store_task_result", None)
        if store_fn is None:
            return
        summary = self._memory_summary(parsed, completion.content)
        try:
            await store_fn(
                task_id or _uuid.uuid4(),
                goal,
                summary[:2000],
                [self.agent_type],
                completion.cost_usd,
                confidence,
            )
        except Exception as exc:  # pragma: no cover - depends on optional deps
            # Memory persistence is an optimization, never a task-killer: a
            # missing vector-store backend (chromadb/sentence_transformers)
            # must not fail an otherwise successful agent run.
            import logging
            logging.getLogger(__name__).warning(
                "success-memory store degraded (skipped): %s", exc
            )

    async def execute(
        self,
        task,
        context: Optional[Dict[str, Any]] = None,
        task_id=None,
    ) -> AgentResult:
        """Run one full agent turn with confidence scoring and LTM storage.

        Lifecycle (mirrors CoderAgent, Step 1.9, so every Phase 2 agent shares
        one implementation): coerce goal → retrieve long-term memory → load
        short-term history → build prompts → LLM call (provider routing via
        ``agent_type``) → parse response → confidence score → store the turn in
        short-term memory → if confidence exceeds ``_store_confidence_threshold``
        store the result in long-term memory for future reuse.

        Concrete agents override ``parse_response`` and ``_calculate_confidence``
        (optionally ``_retrieve_memory`` and ``_store_confidence_threshold``).
        """
        context = context or {}
        goal = self._goal_from_task(task)
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        memory_hits = await self._retrieve_memory(goal)
        history = await self._load_history(task_id)

        system_prompt = self.build_system_prompt(context)
        user_prompt = self.build_user_prompt(goal, context, memory_hits)

        messages: List[LLMMessage] = [LLMMessage("system", system_prompt)]
        for m in history:
            messages.append(LLMMessage(m.get("role", "user"), m.get("content", "")))
        messages.append(LLMMessage("user", user_prompt))

        # The agent span is the child of whatever span is current (the
        # orchestrator's task span) and the parent of the LLM span opened inside
        # ``complete`` — nesting is automatic via OTel's context propagation.
        with self.tracer.agent_span(
            task_id=str(task_id) if task_id else "",
            agent_type=self.agent_type,
            agent_id=self.agent_id,
        ) as span:
            completion: CompletionResult = await self.llm.complete(
                messages,
                provider=self.provider_override,
                agent_type=self.agent_type,
                temperature=self.temperature,
            )

            parsed = self.parse_response(completion.content)
            parsed = await self.post_process(parsed, context, task_id)
            confidence = self._calculate_confidence(parsed)
            reasoning = ""
            if isinstance(parsed, dict):
                for key in self._reasoning_keys:
                    if parsed.get(key):
                        reasoning = str(parsed[key])
                        break

            span.record_llm_usage(
                provider=completion.provider,
                model=completion.model,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                cost_usd=completion.cost_usd,
                agent_type=self.agent_type,
                fallback_used=completion.fallback_used,
            )
            span.set_attribute(AGENT_CONFIDENCE, float(confidence))

        await self._store_turn(task_id, user_prompt, completion.content)

        completed_at = datetime.now(timezone.utc)
        result = AgentResult(
            agent_type=self.agent_type,
            agent_id=self.agent_id,
            provider=completion.provider,
            model=completion.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            content=completion.content,
            parsed=parsed,
            reasoning=reasoning,
            memory_retrieved=memory_hits,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            cost_usd=completion.cost_usd,
            status="completed",
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=time.perf_counter() - t0,
            success=True,
            error=None,
            task_id=task_id,
            confidence_score=confidence,
            fallback_used=completion.fallback_used,
            model_used=completion.model_used,
        )

        if confidence > self._store_confidence_threshold:
            await self._store_success_memory(
                goal, parsed, completion, confidence, task_id
            )

        record_agent_run(
            self.agent_type,
            completion.model,
            True,
            completion.cost_usd,
            completion.input_tokens + completion.output_tokens,
        )

        return result
