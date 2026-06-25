"""Async SQLAlchemy engine, session factory, and table creation."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.profile_context import get_profile_context

engine = create_async_engine(get_profile_context().database_url, echo=False)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with async_session() as session:
        yield session


_RESOLUTION_COLUMNS = {
    "resolved_url": "TEXT",
    "detected_ats": "TEXT",
    "ats_capability": "TEXT",
    "resolution_status": "TEXT",
    "resolution_tier": "TEXT",
}


def _ensure_resolution_columns(sync_conn) -> None:
    """Add the SP1 resolution columns to an existing `contracts` table if missing.

    create_all() creates missing tables but never alters existing ones, so the on-disk
    DB (with real applied history) needs an idempotent ALTER. Safe on a fresh DB too:
    create_all already added the columns, so every column is present and nothing runs."""
    existing = {row[1] for row in sync_conn.exec_driver_sql("PRAGMA table_info(contracts)")}
    for col, sqltype in _RESOLUTION_COLUMNS.items():
        if col not in existing:
            # col/sqltype come from _RESOLUTION_COLUMNS (a module constant), never user
            # input — safe to interpolate (SQLite DDL can't be parameterized anyway).
            sync_conn.exec_driver_sql(f"ALTER TABLE contracts ADD COLUMN {col} {sqltype}")


async def create_tables() -> None:
    """Create all ORM tables if missing, then backfill any missing resolution columns."""
    from backend.db.models import Base  # noqa: F811

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_resolution_columns)
