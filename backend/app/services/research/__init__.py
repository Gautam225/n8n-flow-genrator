"""Tavily web research and technical documentation grounding service."""
from backend.app.services.research.client import TavilyResearchClient
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
    ResearchFinding,
    ResearchSource,
    ResearchUsage,
    StructuredResearchDossier,
)
from backend.app.services.research.service import ResearchService
from backend.app.services.research.validator import ResearchSourceValidator

__all__ = [
    "TavilyResearchClient",
    "ResearchService",
    "ResearchSourceValidator",
    "ResearchSource",
    "ResearchUsage",
    "NormalizedResearchResult",
    "ResearchFinding",
    "StructuredResearchDossier",
    "TavilyClientError",
    "TavilyAuthError",
    "TavilyRateLimitError",
    "TavilyTimeoutError",
    "TavilyAPIError",
    "TavilyUnavailableError",
]
