"""Asynchronous PostgreSQL session management and database engine lifecycle.

Follows SQLAlchemy 2.0 best practices using asyncpg.
Connections are lazily initialized so importing this module never blocks application startup.
"""
from collections.abc import AsyncGenerator
import logging
from typing import Optional, Tuple
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.config import DatabaseSettings

logger = logging.getLogger(__name__)

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_async_engine() -> AsyncEngine:
    """Returns or lazily creates the async SQLAlchemy engine."""
    global _engine
    if _engine is None:
        settings = DatabaseSettings()
        if not settings.DATABASE_URL:
            raise RuntimeError(
                "Cannot initialize database engine: DATABASE_URL is not configured."
            )
        _engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
        )
        logger.info(
            "Created async SQLAlchemy engine for %s",
            settings.get_masked_database_url(),
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Returns or lazily creates the async session factory."""
    global _session_factory
    if _session_factory is None:
        engine = get_async_engine()
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session.

    Ensures proper commit on clean exit, rollback on error, and session close.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database_connection() -> Tuple[bool, str]:
    """Safely tests connectivity to the configured PostgreSQL instance.

    Returns (is_connected, safe_message) without leaking credentials.
    """
    settings = DatabaseSettings()
    if not settings.DATABASE_URL:
        return False, "DATABASE_URL is not configured in backend environment."

    try:
        engine = get_async_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, f"Connected to PostgreSQL database at {settings.get_masked_database_url()}."
    except Exception as e:
        err_type = type(e).__name__
        err_str = str(e)
        logger.warning("Database connectivity check failed: %s", err_type)

        if "password authentication failed" in err_str.lower() or "invalidpassword" in err_str.lower():
            return False, "PostgreSQL authentication failed: invalid username or password."
        if "database" in err_str.lower() and "does not exist" in err_str.lower():
            return False, "Target PostgreSQL database does not exist. It must be created first."
        if "connect" in err_str.lower() or "connection refused" in err_str.lower():
            return False, "Could not establish connection to PostgreSQL server. Verify host and port."
        return False, f"PostgreSQL connection check failed ({err_type})."


async def close_database_engine() -> None:
    """Closes the async engine and cleans up connections."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Disposed async SQLAlchemy engine.")
