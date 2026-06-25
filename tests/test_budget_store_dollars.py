import pytest
from datetime import UTC, datetime

from backend.core.budget_store import display_dollars, period_usage
from backend.db.models import SpendEventDB, SpendKind


def test_display_dollars_prefers_actual():
    assert display_dollars(0.37, 5) == 0.37
    # falls back to estimate when no actual dollars recorded
    assert display_dollars(0.0, 4) == 0.2  # 4 * 0.05


@pytest.mark.asyncio
async def test_period_usage_sums_dollars(db_session):
    now = datetime.now(UTC)
    db_session.add(SpendEventDB(kind=SpendKind.generation, amount=1.0, created_at=now))
    db_session.add(SpendEventDB(kind=SpendKind.generation_dollars, amount=0.12, created_at=now))
    db_session.add(SpendEventDB(kind=SpendKind.connects, amount=10.0, created_at=now))
    await db_session.commit()
    connects, gen_apps, dollars = await period_usage(db_session, now)
    assert connects == 10.0
    assert gen_apps == 1.0
    assert round(dollars, 2) == 0.12
