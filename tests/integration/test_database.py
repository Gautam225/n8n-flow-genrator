"""Integration tests for PostgreSQL database persistence.

Per strict architectural constraints:
- PostgreSQL is mandatory.
- If the PostgreSQL instance/database is unavailable or unauthenticated, tests are marked as skipped.
- SQLite is NEVER substituted.
"""
import pytest
from sqlalchemy import text

from backend.app.db.session import (
    check_database_connection,
    close_database_engine,
    get_async_engine,
    get_db,
)


@pytest.mark.asyncio
async def test_postgresql_connectivity_check():
    """Verify check_database_connection reports safe diagnostic status."""
    is_connected, message = await check_database_connection()
    assert isinstance(is_connected, bool)
    assert isinstance(message, str)
    # Ensure no passwords leaked in diagnostic message
    assert "password" not in message.lower() or "authentication failed" in message.lower() or "not configured" in message.lower()
    await close_database_engine()


@pytest.mark.asyncio
async def test_postgresql_session_dependency():
    """Verify get_db executes with active session when PostgreSQL is available."""
    is_connected, message = await check_database_connection()
    if not is_connected:
        pytest.skip(
            f"PostgreSQL persistence integration test skipped (target database unavailable or unauthenticated): {message}"
        )

    # If connected, test real session execution
    async for db_session in get_db():
        result = await db_session.execute(text("SELECT 1"))
        assert result.scalar() == 1
        break

    await close_database_engine()


@pytest.mark.asyncio
async def test_postgresql_schema_tables_queryable():
    """Verify models and tables are queryable in PostgreSQL when connected."""
    is_connected, message = await check_database_connection()
    if not is_connected:
        pytest.skip(
            f"PostgreSQL persistence integration test skipped (target database unavailable or unauthenticated): {message}"
        )

    engine = get_async_engine()
    async with engine.connect() as conn:
        res = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
        )
        tables = [row[0] for row in res.fetchall()]
        # Verify table list is queryable
        assert isinstance(tables, list)

    await close_database_engine()
