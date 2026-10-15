"""Research Service coordinating planning, caching, Tavily retrieval, and catalog verification."""
from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.app.config import ResearchSettings, get_research_settings
from backend.app.models.conversation import ConversationMessage
from backend.app.services.node_registry import NodeRegistry
from backend.app.services.research.cache import (
    MemoryResearchCache,
    PostgresResearchCache,
    ResearchCacheInterface,
    generate_research_cache_key,
)
from backend.app.services.research.client import TavilyResearchClient
from backend.app.services.research.exceptions import TavilyClientError
from backend.app.services.research.schemas import (
    NormalizedResearchResult,
    ResearchFinding,
    ResearchSource,
    ResearchUsage,
    StructuredResearchDossier,
)

logger = logging.getLogger(__name__)

# Common built-in self-contained integrations that do NOT require external web research
STANDARD_BUILTIN_SERVICES: Set[str] = {
    "gmail", "email", "emailreadimap", "telegram", "googlesheets", "google_sheets",
    "schedule", "cron", "interval", "webhook", "manual", "if", "switch", "code",
    "merge", "set", "filter", "aggregate",
}

# Complex requirement keywords indicating the need for research
COMPLEX_REQUIREMENT_KEYWORDS: List[Tuple[str, str]] = [
    (r"\bpaginat\w*\b|\bcursor\b|\boffset\b|\bnext_url\b", "Pagination and data chunking requirements"),
    (r"\bwebhook\s+payload\b|\bwebhook\s+verification\b|\bhmac\b|\bsignature\b", "Webhook payload schema and security verification"),
    (r"\boauth2\s+scopes?\b|\bapi\s+token\s+headers?\b|\bbearer\b", "Specialized API authentication and permission scopes"),
    (r"\brate\s+limits?\b|\bthrottl\w+\b|\bbackoff\b", "Provider rate limits and quota specifications"),
    (r"\bmulti[- ]branch\w*\b|\bbranches\b|\bbranching\b|\bconditional\s+rout\w+\b|\bstatus\s+code\s+dispatch\b", "Complex multi-branch routing logic"),
    (r"\bstate\s+tracking\b|\bdeduplicat\w+\b|\bpersistent\s+state\b", "Persistent state and deduplication tracking"),
    (r"\berror\s+handl\w+\b|\bretry\s+polic\w+\b|\bfailure\s+paths?\b|\bfault\s+toleran\w+\b", "Fault tolerance and explicit error handling strategy"),
    (r"(?i)\b(research|check\s+doc(s|umentation)?|api\s+doc(s|umentation)?|specifications?)\b", "Explicit user request to research documentation"),
]


class ResearchService:
    """Orchestrates targeted documentation retrieval, caching, and catalog verification."""

    def __init__(
        self,
        client: Optional[TavilyResearchClient] = None,
        cache: Optional[ResearchCacheInterface] = None,
        node_registry: Optional[NodeRegistry] = None,
        settings: Optional[ResearchSettings] = None,
    ):
        self.settings = settings or get_research_settings()
        self.client = client or TavilyResearchClient(settings=self.settings)
        # Use PostgresResearchCache with automatic memory fallback
        self.cache = cache or PostgresResearchCache(default_ttl_seconds=self.settings.TAVILY_CACHE_TTL_HOURS * 3600)
        self.node_registry = node_registry or NodeRegistry()

    def should_research(
        self,
        user_prompt: str,
        history: Optional[List[ConversationMessage]] = None,
        intent: Optional[Any] = None,
    ) -> Tuple[bool, List[str]]:
        """Determines if web research is genuinely necessary.

        Returns (needs_research, reasons). Skips research when local node catalog
        and reliable slot knowledge are fully sufficient.
        """
        reasons: List[str] = []
        prompt_lower = (user_prompt or "").lower()

        # Check explicit research requests or complex technical keywords
        for pattern, desc in COMPLEX_REQUIREMENT_KEYWORDS:
            if re.search(pattern, prompt_lower):
                reasons.append(desc)

        # Inspect target services from prompt and intent
        target_services = self._extract_target_services(user_prompt, intent)
        for svc in target_services:
            svc_norm = svc.lower().replace(" ", "").replace("_", "").replace("-", "")
            # Check if service is outside basic standard built-ins
            if svc_norm not in STANDARD_BUILTIN_SERVICES:
                # Check if installed registry has a verified native node
                node_match = (
                    self.node_registry.get_node(svc)
                    or self.node_registry.get_node(svc_norm)
                    or self.node_registry.get_node(f"n8n-nodes-base.{svc.lower()}")
                    or self.node_registry.get_node(f"n8n-nodes-base.{svc_norm}")
                )
                if not node_match:
                    candidates = self.node_registry.search(svc, limit=2)
                    if not candidates:
                        reasons.append(f"External service '{svc}' has no native n8n node; research needed for HTTP API specifications.")
                    else:
                        reasons.append(f"Technical parameter schema needed for external integration '{svc}'.")
                else:
                    # Native node exists, but user might ask for complex non-standard operation
                    if any(w in prompt_lower for w in ("custom", "advanced", "payload", "filter", "event")):
                        reasons.append(f"Advanced operation or event schema research for '{svc}'.")

        # If user explicitly asks for unknown endpoint or external API
        if any(w in prompt_lower for w in ("http", "endpoint", "rest api", "graphql", "webhook url")):
            if not any("HTTP API specifications" in r for r in reasons):
                reasons.append("Custom API endpoint and payload schema research.")

        # If no complex reasons identified, local catalog is sufficient
        if not reasons:
            return False, ["Local node catalog and built-in definitions are sufficient for standard workflow."]

        return True, reasons

    def _extract_target_services(self, user_prompt: str, intent: Optional[Any] = None) -> List[str]:
        """Identifies target service names from prompt and intent."""
        services: Set[str] = set()

        if intent:
            if getattr(intent, "trigger", None):
                t_svc = getattr(intent.trigger, "service_name", None) or getattr(intent.trigger, "service", None)
                if t_svc:
                    services.add(t_svc)
            for act in getattr(intent, "actions", []):
                a_svc = getattr(act, "service_name", None) or getattr(act, "service", None)
                if a_svc:
                    services.add(a_svc)

        # Keyword heuristics for common services
        known_service_names = [
            "Slack", "Discord", "GitHub", "GitLab", "Google Sheets", "Google Drive",
            "Gmail", "Telegram", "Stripe", "Airtable", "Notion", "Jira", "Shopify",
            "HubSpot", "Salesforce", "Twilio", "SendGrid", "Zendesk", "Trello", "Asana",
        ]
        prompt_lower = (user_prompt or "").lower()
        for name in known_service_names:
            if name.lower() in prompt_lower:
                services.add(name)

        # Extract potential custom service names preceding API / integration / endpoint
        custom_svc_matches = re.findall(
            r"\b([A-Z][a-zA-Z0-9_-]+)\s+(?:custom\s+)?(?:REST\s+)?(?:API|integration|service|endpoint)\b",
            user_prompt,
        )
        for c_svc in custom_svc_matches:
            if c_svc.lower() not in ("custom", "rest", "graphql", "http", "official", "the", "an", "a"):
                services.add(c_svc)

        return list(services)

    def generate_targeted_queries(self, user_prompt: str, intent: Optional[Any] = None) -> List[str]:
        """Formulates targeted search queries for technical documentation."""
        queries: List[str] = []
        services = self._extract_target_services(user_prompt, intent)
        prompt_lower = (user_prompt or "").lower()

        for svc in services[:2]:  # Limit to 2 primary services to prevent quota waste
            # 1. API endpoint & authentication query
            queries.append(f"{svc} official API documentation authentication endpoint request parameters")

            # 2. If webhook or trigger mentioned
            if any(w in prompt_lower for w in ("webhook", "trigger", "event", "listen")):
                queries.append(f"{svc} webhook event payload documentation")
            # 3. If pagination or filtering mentioned
            elif any(w in prompt_lower for w in ("pagination", "filter", "query", "search", "list")):
                queries.append(f"{svc} API pagination and query filters documentation")

        if not queries:
            # Fallback to sanitized prompt focus
            clean_snippet = re.sub(r"[^\w\s-]", "", user_prompt)[:60].strip()
            queries.append(f"{clean_snippet} API documentation specifications")

        # Bounded to max research per turn
        return queries[:self.settings.TAVILY_MAX_RESEARCH_PER_TURN]

    def verify_findings_against_catalog(
        self,
        findings: List[ResearchFinding],
        services: Optional[List[str]] = None,
        target_services: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Matches research findings against installed n8n node definitions (v2.42.6)."""
        compatibility: Dict[str, Any] = {}
        target_svcs = services or target_services or []

        for svc in target_svcs:
            svc_clean = svc.strip().lower()
            svc_no_spaces = svc_clean.replace(" ", "").replace("_", "").replace("-", "")
            direct_node = (
                self.node_registry.get_node(svc_clean)
                or self.node_registry.get_node(svc_no_spaces)
                or self.node_registry.get_node(f"n8n-nodes-base.{svc_clean}")
                or self.node_registry.get_node(f"n8n-nodes-base.{svc_no_spaces}")
            )
            if direct_node:
                svc_nodes = [direct_node]
            else:
                cand_nodes = self.node_registry.search(svc_clean, limit=5)
                svc_nodes = [
                    n for n in cand_nodes
                    if svc_clean in n.name.lower()
                    or svc_no_spaces in n.name.lower()
                    or svc_clean in n.canonical_name.lower()
                    or svc_no_spaces in n.canonical_name.lower()
                    or svc_clean in n.display_name.lower()
                ]
            matched_info: Dict[str, Any] = {
                "service": svc,
                "is_supported": len(svc_nodes) > 0,
                "suggested_node": svc_nodes[0].canonical_name if svc_nodes else "n8n-nodes-base.httpRequest",
                "native_nodes_found": len(svc_nodes),
                "nodes": [],
            }

            if svc_nodes:
                for n in svc_nodes:
                    matched_info["nodes"].append({
                        "name": n.name,
                        "canonical_name": n.canonical_name,
                        "is_trigger": n.is_trigger,
                        "default_version": n.default_version,
                        "supported_versions": n.supported_versions,
                        "operations": n.operations[:6] if n.operations else [],
                        "required_credentials": [cr.name for cr in n.get_expected_credentials()],
                    })
            else:
                matched_info["generic_fallback"] = {
                    "node_type": "n8n-nodes-base.httpRequest",
                    "note": f"No native node for '{svc}'. Use standard HTTP Request node with documented endpoint.",
                    "required_credential_setup": f"Configure generic HTTP header auth or OAuth2 credential in n8n for '{svc}' API.",
                }

            compatibility[svc] = matched_info

        # Mark findings as verified if a native node exists
        for finding in findings:
            finding_text = f"{finding.topic or ''} {finding.fact}".lower()
            for svc, info in compatibility.items():
                if svc.lower() in finding_text:
                    if info.get("nodes"):
                        finding.is_verified_in_catalog = True
                        finding.n8n_node_type = info["nodes"][0]["canonical_name"]

        return compatibility

    def _extract_facts_from_sources(
        self,
        sources: List[ResearchSource],
        target_services: List[str],
    ) -> Tuple[List[ResearchFinding], List[str], List[str]]:
        """Extracts structured technical facts, assumptions, and unresolved questions."""
        facts: List[ResearchFinding] = []
        assumptions: List[str] = []
        unresolved: List[str] = []

        seen_facts: Set[str] = set()

        for src in sources:
            text = f"{src.title}\n{src.snippet}\n{src.content or ''}"

            # 1. Look for API endpoints (HTTP method + path or URL)
            method_matches = re.findall(
                r"\b(POST|GET|PUT|PATCH|DELETE)\s+((?:https?://[a-zA-Z0-9.-]+)?/[a-zA-Z0-9_/.-]+)",
                text,
            )
            for m, ep in method_matches[:3]:
                fact_str = f"API Endpoint: {m} {ep}"
                if fact_str not in seen_facts:
                    seen_facts.add(fact_str)
                    facts.append(ResearchFinding(
                        category="endpoint",
                        fact=fact_str,
                        source_url=src.url,
                    ))

            path_matches = re.findall(
                r"(?:https?://[a-zA-Z0-9.-]+)?((?:/(?:rest|api|v\d+)[a-zA-Z0-9_/.-]+))",
                text,
                re.IGNORECASE,
            )
            for ep in path_matches[:3]:
                fact_str = f"API Endpoint: {ep}"
                if fact_str not in seen_facts:
                    seen_facts.add(fact_str)
                    facts.append(ResearchFinding(
                        category="endpoint",
                        fact=fact_str,
                        source_url=src.url,
                    ))

            # 2. Look for Authentication requirements
            if re.search(r"(?i)\bbearer\s+token\b|\boauth2\b|\bapi[ -]key\b", text):
                auth_desc = "Bearer Token or OAuth2 API authentication required."
                if auth_desc not in seen_facts:
                    seen_facts.add(auth_desc)
                    facts.append(ResearchFinding(
                        category="authentication",
                        fact=auth_desc,
                        source_url=src.url,
                    ))

            # 3. Look for Pagination requirements
            if re.search(r"(?i)\bcursor\b|\blimit\b|\boffset\b|\bpage_size\b", text):
                pag_desc = "Pagination supported via limit/offset or cursor parameters."
                if pag_desc not in seen_facts:
                    seen_facts.add(pag_desc)
                    facts.append(ResearchFinding(
                        category="pagination",
                        fact=pag_desc,
                        source_url=src.url,
                    ))

            # 4. Look for Rate Limit hints
            rate_match = re.search(r"(?i)(\d+)\s+requests\s+per\s+(minute|second|hour)", text)
            if rate_match:
                rate_desc = f"Rate limit documented: {rate_match.group(0)}"
                if rate_desc not in seen_facts:
                    seen_facts.add(rate_desc)
                    facts.append(ResearchFinding(
                        category="rate_limits",
                        fact=rate_desc,
                        source_url=src.url,
                    ))

            # 5. Look for Webhook security / signature requirements
            if re.search(r"(?i)\b(hmac|signature|webhook\s+secret|verify\s+signature)\b", text):
                hook_desc = "Webhook signature verification required using HMAC header."
                if hook_desc not in seen_facts:
                    seen_facts.add(hook_desc)
                    facts.append(ResearchFinding(
                        category="security",
                        fact=hook_desc,
                        source_url=src.url,
                    ))

        # Default inferences if no specific facts were found
        if not facts and target_services:
            for svc in target_services:
                assumptions.append(f"Assumed standard REST API conventions apply for {svc}.")

        return facts, assumptions, unresolved

    async def conduct_research(
        self,
        user_prompt: str,
        history: Optional[List[ConversationMessage]] = None,
        intent: Optional[Any] = None,
    ) -> StructuredResearchDossier:
        """Executes targeted web research, caches results, and verifies against local node definitions."""
        needs_research, reasons = self.should_research(user_prompt, history, intent)
        target_services = self._extract_target_services(user_prompt, intent)

        # If research is not needed, return minimal dossier
        if not needs_research:
            return StructuredResearchDossier(
                user_query=user_prompt,
                needs_research=False,
                research_reasons=reasons,
                target_services=target_services,
                node_compatibility=self.verify_findings_against_catalog([], target_services),
            )

        # Check if Tavily API key is configured
        if not self.settings.is_configured:
            logger.info("Tavily API key is not configured. Falling back to local node catalog.")
            return StructuredResearchDossier(
                user_query=user_prompt,
                needs_research=True,
                research_reasons=reasons,
                target_services=target_services,
                node_compatibility=self.verify_findings_against_catalog([], target_services),
                warnings=["TAVILY_API_KEY is not configured; grounded planning using installed node catalog only."],
                is_fallback=True,
            )

        queries = self.generate_targeted_queries(user_prompt, intent)
        all_sources: List[ResearchSource] = []
        usage = ResearchUsage()
        warnings: List[str] = []

        # Execute searches with caching
        for q in queries:
            cache_key = generate_research_cache_key(q, self.settings.TAVILY_SEARCH_DEPTH)
            cached_result = await self.cache.get(cache_key)

            if cached_result:
                usage.cached_hits += 1
                all_sources.extend(cached_result.sources)
                continue

            try:
                search_res = await self.client.search(
                    query=q,
                    search_depth=self.settings.TAVILY_SEARCH_DEPTH,
                    max_results=self.settings.TAVILY_MAX_RESULTS,
                    include_answer=True,
                    include_raw_content=False,
                )
                usage.searches_count += 1
                usage.total_chars += search_res.usage.total_chars
                all_sources.extend(search_res.sources)

                # Store in cache
                await self.cache.set(cache_key, search_res, self.settings.TAVILY_CACHE_TTL_HOURS * 3600)

            except TavilyClientError as err:
                logger.warning("Tavily research query '%s' failed: %s", q, str(err))
                warnings.append(f"Search for '{q}' encountered limitation: {err.message}")
            except Exception as ex:
                logger.warning("Unexpected Tavily error for query '%s': %s", q, str(ex))
                warnings.append(f"Unexpected research error for query '{q}'.")

        # Deduplicate all collected sources
        from backend.app.services.research.validator import ResearchSourceValidator
        deduped_sources = ResearchSourceValidator.deduplicate_sources(all_sources)

        # Extract facts, assumptions, and unresolved questions
        facts, assumptions, unresolved = self._extract_facts_from_sources(deduped_sources, target_services)

        # Verify against local n8n NodeRegistry
        node_compat = self.verify_findings_against_catalog(facts, target_services)

        return StructuredResearchDossier(
            user_query=user_prompt,
            needs_research=True,
            research_reasons=reasons,
            target_services=target_services,
            queries_executed=queries,
            sources=deduped_sources,
            documented_facts=facts,
            assumptions=assumptions,
            unresolved_questions=unresolved,
            node_compatibility=node_compat,
            usage=usage,
            warnings=warnings,
            is_fallback=bool(warnings and not deduped_sources),
        )
