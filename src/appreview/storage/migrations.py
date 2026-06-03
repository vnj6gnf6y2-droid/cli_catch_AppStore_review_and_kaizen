"""Database migrations — idempotent CREATE TABLE IF NOT EXISTS approach."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from appreview.storage.models import Base


async def run_migrations(engine: AsyncEngine) -> None:
    """Create all tables if they don't exist.

    This is a lightweight, Alembic-free migration strategy suitable for v0.1.0.
    All CREATE TABLE statements are idempotent (IF NOT EXISTS).

    Args:
        engine: Async SQLAlchemy engine connected to the database.
    """
    async with engine.begin() as conn:
        # Enable WAL mode for better concurrent read performance with SQLite
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        # Create all tables defined in the ORM models.
        # checkfirst=True makes every CREATE TABLE and CREATE INDEX idempotent.
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=True))
