import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from backend.db.database import _ensure_resolution_columns

_NEW_COLS = {"resolved_url", "detected_ats", "ats_capability", "resolution_status", "resolution_tier"}


@pytest.mark.asyncio
async def test_ensure_resolution_columns_adds_missing_and_is_idempotent():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        # Simulate an OLD contracts table that predates the resolution columns.
        await conn.exec_driver_sql("CREATE TABLE contracts (id INTEGER PRIMARY KEY, url TEXT)")
        await conn.run_sync(_ensure_resolution_columns)
        cols = {row[1] for row in (await conn.exec_driver_sql("PRAGMA table_info(contracts)")).fetchall()}
        assert _NEW_COLS <= cols
        # Idempotent: running again must not raise (no duplicate ADD COLUMN).
        await conn.run_sync(_ensure_resolution_columns)
    await engine.dispose()
