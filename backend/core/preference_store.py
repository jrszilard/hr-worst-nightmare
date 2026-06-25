"""DB helpers for the learned skill-preference weights (skill_preferences table)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import SkillPreferenceDB


class PreferenceStore:
    @staticmethod
    async def load_weights(session: AsyncSession) -> dict[str, float]:
        rows = (await session.execute(select(SkillPreferenceDB))).scalars().all()
        return {r.skill: r.weight for r in rows}

    @staticmethod
    async def save_weights(
        session: AsyncSession, weights: dict[str, float], commit: bool = True
    ) -> None:
        """Upsert each skill's weight. Rows are kept even at 0.0 (history).

        Pass commit=False to participate in a caller-managed transaction.
        """
        existing = {
            r.skill: r
            for r in (await session.execute(select(SkillPreferenceDB))).scalars().all()
        }
        for skill, weight in weights.items():
            row = existing.get(skill)
            if row is None:
                session.add(SkillPreferenceDB(skill=skill, weight=weight))
            else:
                row.weight = weight
        if commit:
            await session.commit()
