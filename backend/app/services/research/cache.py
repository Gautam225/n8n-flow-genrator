"""Cache interface and implementations for Tavily web research results."""
from abc import ABC, abstractmethod
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import time
from typing import Dict, Optional, Tuple

from backend.app.services.research.schemas import NormalizedResearchResult

logger = logging.getLogger(__name__)


def generate_research_cache_key(query: str, search_depth: str = "basic") -> str:
    """Generates a deterministic hash key for a query and depth configuration."""
    normalized = f"{query.strip().lower()}:{search_depth.strip().lower()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class ResearchCacheInterface(ABC):
    """Abstract interface for research caching."""

    @abstractmethod
    async def get(self, key: str) -> Optional[NormalizedResearchResult]:
        """Retrieves a cached research result if not expired."""
        pass

    @abstractmethod
    async def set(self, key: str, result: NormalizedResearchResult, ttl_seconds: Optional[int] = None) -> None:
        """Stores a normalized research result with specified TTL."""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clears all cached entries."""
        pass


class MemoryResearchCache(ResearchCacheInterface):
    """Thread-safe and async-safe in-memory LRU cache with TTL expiration."""

    def __init__(self, max_entries: int = 200, default_ttl_seconds: int = 86400):
        self._max_entries = max_entries
        self._default_ttl_seconds = default_ttl_seconds
        self._cache: Dict[str, Tuple[NormalizedResearchResult, float, float]] = {}  # key -> (result, expires_at, last_access)
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[NormalizedResearchResult]:
        async with self._lock:
            if key not in self._cache:
                return None

            result, expires_at, _ = self._cache[key]
            now = time.time()
            if now > expires_at:
                del self._cache[key]
                return None

            # Update access time for LRU
            self._cache[key] = (result, expires_at, now)
            return result

    async def set(self, key: str, result: NormalizedResearchResult, ttl_seconds: Optional[int] = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl_seconds
        now = time.time()
        expires_at = now + ttl

        async with self._lock:
            # Enforce max entries with LRU eviction
            if len(self._cache) >= self._max_entries and key not in self._cache:
                # Evict oldest by last_access
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][2])
                del self._cache[oldest_key]

            self._cache[key] = (result, expires_at, now)

    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)


class PostgresResearchCache(ResearchCacheInterface):
    """Persistent PostgreSQL research cache with clean automatic fallback to in-memory caching."""

    def __init__(self, default_ttl_seconds: int = 86400):
        self._default_ttl_seconds = default_ttl_seconds
        self._memory_fallback = MemoryResearchCache(default_ttl_seconds=default_ttl_seconds)

    async def get(self, key: str) -> Optional[NormalizedResearchResult]:
        # Always check memory fallback first
        mem_hit = await self._memory_fallback.get(key)
        if mem_hit:
            return mem_hit

        try:
            from backend.app.db.session import check_database_connection, get_async_engine
            from sqlalchemy import text

            is_connected, _ = await check_database_connection()
            if not is_connected:
                return None

            engine = get_async_engine()
            async with engine.connect() as conn:
                query = text(
                    "SELECT result_json, expires_at FROM research_cache WHERE cache_key = :k"
                )
                res = await conn.execute(query, {"k": key})
                row = res.fetchone()
                if not row:
                    return None

                result_json, expires_at = row
                now = datetime.now(timezone.utc)
                if expires_at and expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)

                if expires_at and now > expires_at:
                    return None

                data = json.loads(result_json) if isinstance(result_json, str) else result_json
                norm_res = NormalizedResearchResult.model_validate(data)
                # Store in memory cache for faster subsequent reads
                await self._memory_fallback.set(key, norm_res, self._default_ttl_seconds)
                return norm_res
        except Exception as e:
            logger.debug("PostgreSQL research cache read fallback: %s", str(e))
            return None

    async def set(self, key: str, result: NormalizedResearchResult, ttl_seconds: Optional[int] = None) -> None:
        # Always store in memory fallback
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl_seconds
        await self._memory_fallback.set(key, result, ttl)

        try:
            from backend.app.db.session import check_database_connection, get_async_engine
            from sqlalchemy import text

            is_connected, _ = await check_database_connection()
            if not is_connected:
                return

            engine = get_async_engine()
            now = datetime.now(timezone.utc)
            expires_at = datetime.fromtimestamp(time.time() + ttl, timezone.utc)
            data_json = json.dumps(result.model_dump(mode="json"))

            async with engine.begin() as conn:
                # Ensure research_cache table exists
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS research_cache (
                        cache_key VARCHAR(255) PRIMARY KEY,
                        query TEXT NOT NULL,
                        result_json JSONB NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP WITH TIME ZONE NOT NULL
                    )
                """))
                await conn.execute(text("""
                    INSERT INTO research_cache (cache_key, query, result_json, created_at, expires_at)
                    VALUES (:k, :q, :rj, :c, :e)
                    ON CONFLICT (cache_key) DO UPDATE SET
                        result_json = EXCLUDED.result_json,
                        expires_at = EXCLUDED.expires_at
                """), {
                    "k": key,
                    "q": result.query,
                    "rj": data_json,
                    "c": now,
                    "e": expires_at,
                })
        except Exception as e:
            logger.debug("PostgreSQL research cache write fallback: %s", str(e))

    async def clear(self) -> None:
        await self._memory_fallback.clear()
        try:
            from backend.app.db.session import check_database_connection, get_async_engine
            from sqlalchemy import text

            is_connected, _ = await check_database_connection()
            if not is_connected:
                return

            engine = get_async_engine()
            async with engine.begin() as conn:
                await conn.execute(text("TRUNCATE TABLE research_cache"))
        except Exception as e:
            logger.debug("PostgreSQL research cache clear fallback: %s", str(e))
