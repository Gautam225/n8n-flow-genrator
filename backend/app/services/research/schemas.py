"""Data models and schemas for Tavily web research and technical documentation grounding."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ResearchSource(BaseModel):
    """Normalized research document or web reference."""

    title: str = Field(description="Page or document title")
    url: str = Field(description="Canonical URL of the source")
    snippet: str = Field(default="", description="Relevant snippet extracted from search or summary")
    content: Optional[str] = Field(default=None, description="Cleaned, sanitized page text or markdown extract")
    score: float = Field(default=0.0, description="Relevance score assigned by Tavily or ranker")
    source_type: str = Field(
        default="generic_web",
        description="Source classification: 'official_docs', 'community', or 'generic_web'",
    )
    version_info: Optional[str] = Field(default=None, description="API or library version mentioned in source")
    retrieved_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp of retrieval",
    )
    query: str = Field(default="", description="Search query that surfaced this source")


class ResearchUsage(BaseModel):
    """Tracks research budget consumption and caching efficiency."""

    searches_count: int = Field(default=0, description="Number of web search requests executed")
    extractions_count: int = Field(default=0, description="Number of direct page extraction requests executed")
    cached_hits: int = Field(default=0, description="Number of responses served from cache")
    total_chars: int = Field(default=0, description="Total characters processed from sources")


class NormalizedResearchResult(BaseModel):
    """Internal standardized format for Tavily search or extract responses."""

    query: str
    sources: List[ResearchSource] = Field(default_factory=list)
    synthesized_summary: Optional[str] = Field(default=None, description="Tavily or LLM synthesized answer")
    retrieval_metadata: Dict[str, Any] = Field(default_factory=dict)
    usage: ResearchUsage = Field(default_factory=ResearchUsage)


class ResearchFinding(BaseModel):
    """A specific factual takeaway extracted from official documentation."""

    category: str = Field(
        description="Category: 'endpoint', 'authentication', 'payload_format', 'branch_logic', 'pagination', 'rate_limits', 'error_handling'"
    )
    topic: Optional[str] = Field(default=None, description="Short topic or service name")
    fact: str = Field(description="Precise technical requirement, endpoint URL, header, or configuration detail")
    source_url: Optional[str] = Field(default=None, description="URL where this fact was verified")
    is_verified_in_catalog: bool = Field(default=False, description="Whether this finding maps to installed n8n node capabilities")
    n8n_node_type: Optional[str] = Field(default=None, description="Matching installed n8n node type if applicable")


class StructuredResearchDossier(BaseModel):
    """Comprehensive research dossier passed into workflow planning and synthesis."""

    user_query: str
    needs_research: bool = Field(default=False, description="Whether web research was deemed necessary")
    research_reasons: List[str] = Field(default_factory=list, description="Reasons why research was or was not performed")
    target_services: List[str] = Field(default_factory=list, description="Services identified for research")
    queries_executed: List[str] = Field(default_factory=list, description="Targeted queries sent to search")
    sources: List[ResearchSource] = Field(default_factory=list, description="Deduplicated and validated sources")
    documented_facts: List[ResearchFinding] = Field(default_factory=list, description="Verified technical facts")
    assumptions: List[str] = Field(default_factory=list, description="Inferred assumptions where documentation was incomplete")
    unresolved_questions: List[str] = Field(default_factory=list, description="Genuinely missing inputs requiring user clarification")
    node_compatibility: Dict[str, Any] = Field(
        default_factory=dict,
        description="Catalog matching findings, supported operations, and required credential types",
    )
    usage: ResearchUsage = Field(default_factory=ResearchUsage)
    warnings: List[str] = Field(default_factory=list, description="Warnings or limitations encountered during research")
    is_fallback: bool = Field(default=False, description="True if research failed or was skipped due to missing API key")
