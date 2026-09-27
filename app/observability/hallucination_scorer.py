"""Hallucination score persistence and tenant aggregates (Step 4.3)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.hallucination_score import HallucinationScoreRecord
from app.observability.metrics import record_hallucination_score


class HallucinationScorer:
    """Persist scores, maintain a Redis rolling average, emit Prometheus metrics."""

    def __init__(
        self,
        db_session: Optional[AsyncSession] = None,
        redis_client: Any = None,
    ) -> None:
        self.db_session = db_session
        self.redis_client = redis_client

    def _redis_key(self, tenant_id: str) -> str:
        return f"hallucination:avg:{tenant_id}"

    async def record_score(
        self,
        task_id: str,
        agent_type: str,
        score: float,
        verdict: str,
        tenant_id: str,
    ) -> None:
        record_hallucination_score(score)
        if self.db_session is not None:
            row = HallucinationScoreRecord(
                task_id=uuid.UUID(task_id),
                tenant_id=uuid.UUID(tenant_id),
                agent_type=agent_type or "hallucination_detector",
                score=float(score),
                verdict=verdict or ("pass" if score >= 0.7 else "fail"),
            )
            self.db_session.add(row)
            await self.db_session.flush()

        redis = self.redis_client
        if redis is None:
            try:
                from app.security.redis_client import get_redis

                redis = get_redis()
            except Exception:
                redis = None
        if redis is not None:
            key = self._redis_key(tenant_id)
            try:
                raw = await redis.get(key)
                if raw:
                    data = json.loads(raw)
                    count = int(data.get("count", 0)) + 1
                    total = float(data.get("total", 0.0)) + float(score)
                else:
                    count, total = 1, float(score)
                payload = json.dumps({"count": count, "total": total})
                await redis.set(key, payload, ex=30 * 24 * 3600)
            except Exception:
                pass

    async def get_tenant_average(self, tenant_id: str) -> float:
        redis = self.redis_client
        if redis is None:
            try:
                from app.security.redis_client import get_redis

                redis = get_redis()
            except Exception:
                redis = None
        if redis is not None:
            try:
                raw = await redis.get(self._redis_key(tenant_id))
                if raw:
                    data = json.loads(raw)
                    count = int(data.get("count", 0))
                    total = float(data.get("total", 0.0))
                    if count > 0:
                        return round(total / count, 4)
            except Exception:
                pass

        if self.db_session is None:
            return 0.0
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        avg = (
            await self.db_session.execute(
                select(func.avg(HallucinationScoreRecord.score)).where(
                    HallucinationScoreRecord.tenant_id == uuid.UUID(tenant_id),
                    HallucinationScoreRecord.recorded_at >= cutoff,
                )
            )
        ).scalar_one()
        return round(float(avg or 0.0), 4)

    async def get_agent_scores(
        self, agent_type: str, tenant_id: str, days: int = 30
    ) -> List[dict]:
        if self.db_session is None:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(HallucinationScoreRecord)
            .where(
                HallucinationScoreRecord.tenant_id == uuid.UUID(tenant_id),
                HallucinationScoreRecord.agent_type == agent_type,
                HallucinationScoreRecord.recorded_at >= cutoff,
            )
            .order_by(HallucinationScoreRecord.recorded_at.desc())
            .limit(200)
        )
        rows = (await self.db_session.execute(stmt)).scalars().all()
        return [
            {
                "task_id": str(r.task_id),
                "score": r.score,
                "verdict": r.verdict,
                "recorded_at": r.recorded_at.isoformat(),
            }
            for r in rows
        ]

    async def get_tenant_breakdown(
        self, tenant_id: str, days: int = 30
    ) -> Dict[str, Any]:
        """Tenant average, per-agent averages, and recent history for the API."""
        if self.db_session is None:
            return {
                "tenant_average": await self.get_tenant_average(tenant_id),
                "by_agent": {},
                "recent": [],
            }
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = (
            await self.db_session.execute(
                select(HallucinationScoreRecord)
                .where(
                    HallucinationScoreRecord.tenant_id == uuid.UUID(tenant_id),
                    HallucinationScoreRecord.recorded_at >= cutoff,
                )
                .order_by(HallucinationScoreRecord.recorded_at.desc())
                .limit(500)
            )
        ).scalars().all()

        by_agent: Dict[str, List[float]] = {}
        for r in rows:
            by_agent.setdefault(r.agent_type, []).append(r.score)

        return {
            "tenant_average": await self.get_tenant_average(tenant_id),
            "by_agent": {
                agent: round(sum(scores) / len(scores), 4)
                for agent, scores in by_agent.items()
            },
            "recent": [
                {
                    "agent_type": r.agent_type,
                    "score": r.score,
                    "verdict": r.verdict,
                    "task_id": str(r.task_id),
                    "recorded_at": r.recorded_at.isoformat(),
                }
                for r in rows[:50]
            ],
        }
