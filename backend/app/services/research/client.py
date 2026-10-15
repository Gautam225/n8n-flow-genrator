"""Typed, asynchronous Tavily research client with retries, timeouts, rate-limit safety, and normalization."""
import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
import httpx

from backend.app.config import ResearchSettings, get_research_settings
from backend.app.services.research.exceptions import (
    TavilyAPIError,
    TavilyAuthError,
    TavilyClientError,
    TavilyRateLimitError,
    TavilyTimeoutError,
    TavilyUnavailableError,
)
from backend.app.services.research.schemas import (
    NormalizedResearchResult,
    ResearchSource,
    ResearchUsage,
)
from backend.app.services.research.validator import ResearchSourceValidator

logger = logging.getLogger(__name__)


class TavilyResearchClient:
    """Async client for Tavily Search and Extract APIs with safe error handling and normalization."""

    def __init__(
        self,
        settings: Optional[ResearchSettings] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.settings = settings or get_research_settings()
        self._http_client = http_client
        self.usage = ResearchUsage()

    def _get_masked_key(self) -> str:
        """Returns safe masked key for diagnostic logging."""
        key = self.settings.TAVILY_API_KEY or ""
        if len(key) <= 8:
            return "***"
        return f"{key[:4]}...{key[-4:]}"

    def _build_headers(self) -> Dict[str, str]:
        """Constructs headers for Tavily API."""
        api_key = (self.settings.TAVILY_API_KEY or "").strip()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    async def _post_with_retries(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Executes HTTP POST request with bounded exponential backoff retries."""
        if not self.settings.is_configured:
            raise TavilyAuthError("Tavily API key is not configured. Web research cannot proceed.")

        # Ensure api_key is also present in body for broad Tavily endpoint compatibility
        if "api_key" not in payload and self.settings.TAVILY_API_KEY:
            payload["api_key"] = self.settings.TAVILY_API_KEY.strip()

        base_url = self.settings.TAVILY_BASE_URL.rstrip("/")
        target_url = f"{base_url}{endpoint}"
        headers = self._build_headers()
        timeout = httpx.Timeout(self.settings.TAVILY_TIMEOUT_SEC, connect=10.0)

        max_retries = self.settings.TAVILY_MAX_RETRIES
        delay = 1.0

        for attempt in range(max_retries + 1):
            client = self._http_client or httpx.AsyncClient(timeout=timeout)
            try:
                logger.debug(
                    "Tavily request to %s (attempt %d/%d, key: %s)",
                    endpoint,
                    attempt + 1,
                    max_retries + 1,
                    self._get_masked_key(),
                )
                response = await client.post(target_url, json=payload, headers=headers)

                # Check HTTP status
                if response.status_code == 200:
                    return response.json()

                if response.status_code in (401, 403):
                    logger.warning("Tavily authentication failure (HTTP %d).", response.status_code)
                    raise TavilyAuthError(f"Tavily authentication failed (HTTP {response.status_code}).")

                if response.status_code == 429:
                    retry_after = 5.0
                    if "Retry-After" in response.headers:
                        try:
                            retry_after = float(response.headers["Retry-After"])
                        except Exception:
                            pass
                    logger.warning("Tavily rate limit hit (HTTP 429). Retry-after: %.1fs", retry_after)
                    if attempt < max_retries:
                        await asyncio.sleep(min(retry_after, 5.0))
                        continue
                    raise TavilyRateLimitError(retry_after=retry_after)

                if response.status_code >= 500:
                    logger.warning(
                        "Tavily server error (HTTP %d): %s (attempt %d/%d)",
                        response.status_code,
                        response.text[:200],
                        attempt + 1,
                        max_retries + 1,
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(delay)
                        delay *= 2.0
                        continue
                    raise TavilyAPIError(
                        message=f"Tavily server returned HTTP {response.status_code}",
                        status_code=response.status_code,
                    )

                # Other 4xx client errors
                err_text = response.text[:250]
                raise TavilyAPIError(
                    message=f"Tavily API error: HTTP {response.status_code} - {err_text}",
                    status_code=response.status_code,
                )

            except (httpx.TimeoutException, asyncio.TimeoutError):
                logger.warning("Tavily request timed out on %s (attempt %d/%d).", endpoint, attempt + 1, max_retries + 1)
                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 1.5
                    continue
                raise TavilyTimeoutError(f"Tavily request timed out after {self.settings.TAVILY_TIMEOUT_SEC}s.")

            except httpx.NetworkError as net_err:
                logger.warning("Tavily network error on %s: %s (attempt %d/%d).", endpoint, str(net_err), attempt + 1, max_retries + 1)
                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 1.5
                    continue
                raise TavilyUnavailableError(f"Tavily service is unreachable: {str(net_err)}")

            finally:
                if self._http_client is None:
                    await client.aclose()

        raise TavilyUnavailableError("Tavily request failed after retries.")

    async def search(
        self,
        query: str,
        search_depth: Optional[str] = None,
        max_results: Optional[int] = None,
        include_answer: bool = True,
        include_raw_content: bool = False,
    ) -> NormalizedResearchResult:
        """Executes a real-time web search optimized for technical documentation."""
        clean_query = query.strip()
        if not clean_query:
            return NormalizedResearchResult(query="")

        depth = search_depth or self.settings.TAVILY_SEARCH_DEPTH
        limit = max_results or self.settings.TAVILY_MAX_RESULTS

        payload = {
            "query": clean_query,
            "search_depth": depth,
            "max_results": limit,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
        }

        raw_data = await self._post_with_retries("/search", payload)
        self.usage.searches_count += 1

        # Process and normalize raw results
        raw_results = raw_data.get("results", [])
        synthesized_answer = raw_data.get("answer")
        resp_time = raw_data.get("response_time", 0.0)

        normalized_sources: List[ResearchSource] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        total_chars = 0

        for item in raw_results:
            raw_url = item.get("url", "")
            is_safe, reason = ResearchSourceValidator.is_safe_url(raw_url)
            if not is_safe:
                logger.warning("Discarding unsafe search result URL '%s': %s", raw_url, reason)
                continue

            title = item.get("title", "")
            snippet = item.get("content", "")
            raw_content = item.get("raw_content")
            score = float(item.get("score", 0.0))

            # Sanitize content
            clean_snippet = ResearchSourceValidator.sanitize_content(
                snippet,
                max_chars=self.settings.TAVILY_MAX_CONTENT_CHARS,
            )
            clean_content = None
            if raw_content:
                clean_content = ResearchSourceValidator.sanitize_content(
                    raw_content,
                    max_chars=self.settings.TAVILY_MAX_CONTENT_CHARS,
                )

            # Extract version hints and domain authority
            authority = ResearchSourceValidator.classify_domain_authority(raw_url)
            combined_text = f"{title} {clean_snippet} {clean_content or ''}"
            version_info = ResearchSourceValidator.extract_version_hints(combined_text)

            source = ResearchSource(
                title=title,
                url=raw_url,
                snippet=clean_snippet,
                content=clean_content,
                score=score,
                source_type=authority,
                version_info=version_info,
                retrieved_at=now_iso,
                query=clean_query,
            )
            normalized_sources.append(source)
            total_chars += len(clean_snippet) + (len(clean_content) if clean_content else 0)

        # Deduplicate sources while retaining highest score
        deduped = ResearchSourceValidator.deduplicate_sources(normalized_sources)
        self.usage.total_chars += total_chars

        return NormalizedResearchResult(
            query=clean_query,
            sources=deduped,
            synthesized_summary=synthesized_answer,
            retrieval_metadata={
                "search_depth": depth,
                "response_time": resp_time,
                "raw_count": len(raw_results),
                "filtered_count": len(deduped),
            },
            usage=self.usage,
        )

    async def extract(
        self,
        urls: List[str],
        extract_depth: str = "basic",
        format_type: str = "markdown",
    ) -> List[ResearchSource]:
        """Extracts structured text from specific target documentation URLs."""
        if not urls:
            return []

        # Validate URLs for SSRF safety
        safe_urls: List[str] = []
        for u in urls:
            is_safe, reason = ResearchSourceValidator.is_safe_url(u)
            if is_safe:
                safe_urls.append(u)
            else:
                logger.warning("Skipping unsafe extract target URL '%s': %s", u, reason)

        if not safe_urls:
            return []

        # Limit batch size to max extracts per turn
        safe_urls = safe_urls[:self.settings.TAVILY_MAX_EXTRACT_PER_TURN]

        payload = {
            "urls": safe_urls,
            "extract_depth": extract_depth,
            "format": format_type,
        }

        raw_data = await self._post_with_retries("/extract", payload)
        self.usage.extractions_count += len(safe_urls)

        results: List[ResearchSource] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        total_chars = 0

        for item in raw_data.get("results", []):
            url = item.get("url", "")
            raw_content = item.get("raw_content", "")
            clean_content = ResearchSourceValidator.sanitize_content(
                raw_content,
                max_chars=self.settings.TAVILY_MAX_CONTENT_CHARS,
            )
            authority = ResearchSourceValidator.classify_domain_authority(url)
            version_info = ResearchSourceValidator.extract_version_hints(clean_content)

            source = ResearchSource(
                title=f"Documentation: {url}",
                url=url,
                snippet=clean_content[:300] if clean_content else "",
                content=clean_content,
                score=1.0,
                source_type=authority,
                version_info=version_info,
                retrieved_at=now_iso,
                query="direct_extract",
            )
            results.append(source)
            total_chars += len(clean_content)

        self.usage.total_chars += total_chars
        return results
