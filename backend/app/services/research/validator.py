"""Validation, sanitization, domain authority scoring, and deduplication for research sources."""
import ipaddress
import re
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from backend.app.services.research.schemas import ResearchSource

# Recognized official developer and documentation domains
OFFICIAL_DOC_DOMAINS: Set[str] = {
    "docs.n8n.io",
    "n8n.io",
    "api.slack.com",
    "docs.github.com",
    "developers.google.com",
    "stripe.com",
    "core.telegram.org",
    "developers.notion.com",
    "airtable.com",
    "docs.sendgrid.com",
    "twilio.com",
    "developer.salesforce.com",
    "developer.spotify.com",
    "developer.twitter.com",
    "docs.aws.amazon.com",
    "learn.microsoft.com",
    "docs.gitlab.com",
    "atlassian.com",
    "developer.atlassian.com",
    "developers.hubspot.com",
    "shopify.dev",
    "docs.stripe.com",
    "platform.openai.com",
    "docs.anthropic.com",
}

COMMUNITY_DOMAINS: Set[str] = {
    "community.n8n.io",
    "stackoverflow.com",
    "stackexchange.com",
    "github.com",
    "reddit.com",
}

# Prompt injection and malicious jailbreak patterns in external web content
PROMPT_INJECTION_PATTERNS: List[Tuple[str, str]] = [
    (r"(?i)\b(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|directives)\b", "instruction override"),
    (r"(?i)\byou\s+are\s+now\s+(a\s+)?(new|different|unrestricted|jailbroken)\b", "persona hijack"),
    (r"(?i)\b(system\s*prompt|system\s*instructions|system\s*message)\b", "system prompt leakage attempt"),
    (r"(?i)\b(do\s+not\s+follow|bypass)\s+(safety|policy|rules)\b", "safety bypass attempt"),
]

TRACKING_QUERY_PARAMS: Set[str] = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "fbclid", "gclid",
}


class ResearchSourceValidator:
    """Validates external URLs, scores source authority, sanitizes untrusted web content, and deduplicates."""

    @classmethod
    def is_safe_url(cls, url: str) -> Tuple[bool, Optional[str]]:
        """Verifies URL safety and protects against Server-Side Request Forgery (SSRF)."""
        if not url or not isinstance(url, str):
            return False, "URL is empty or invalid"

        clean = url.strip()
        try:
            parsed = urlparse(clean)
        except Exception:
            return False, "Failed to parse URL"

        if parsed.scheme not in ("http", "https"):
            return False, f"Invalid URL scheme '{parsed.scheme}'. Only http and https are allowed."

        host = (parsed.hostname or "").lower()
        if not host:
            return False, "Missing hostname in URL"

        # Check blocked cloud metadata and internal hostnames
        cloud_metadata_hosts = {
            "169.254.169.254",
            "metadata.google.internal",
            "instance-data",
            "metadata.nic.internal",
            "localhost",
            "127.0.0.1",
            "::1",
        }
        if host in cloud_metadata_hosts or host.startswith("169.254."):
            return False, f"Blocked by SSRF policy (metadata/link-local host '{host}')"

        # Check IP representations for private/link-local/loopback addresses
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_link_local or ip.is_loopback:
                return False, f"Blocked by SSRF policy (private or loopback IP '{host}')"
        except ValueError:
            pass

        return True, None

    @classmethod
    def classify_domain_authority(cls, url: str) -> str:
        """Classifies source domain into 'official_docs', 'community', or 'generic_web'."""
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
        except Exception:
            return "generic_web"

        # 1. Exact hostname match
        if host in OFFICIAL_DOC_DOMAINS:
            return "official_docs"
        if host in COMMUNITY_DOMAINS:
            return "community"

        # 2. Common developer and documentation subdomains
        if any(host.startswith(prefix) for prefix in ("docs.", "developer.", "developers.", "api.")):
            return "official_docs"

        # 3. Known community subdomains
        if any(host.startswith(prefix) for prefix in ("community.", "forum.", "discuss.")):
            return "community"

        # 4. Suffix matching
        for official in OFFICIAL_DOC_DOMAINS:
            if host.endswith(f".{official}"):
                return "official_docs"

        for community in COMMUNITY_DOMAINS:
            if host.endswith(f".{community}"):
                return "community"

        return "generic_web"

    @classmethod
    def normalize_url(cls, url: str) -> str:
        """Normalizes URL for accurate deduplication by stripping tracking query params and trailing slashes."""
        try:
            parsed = urlparse(url.strip())
            # Strip tracking query parameters
            query_items = parse_qsl(parsed.query, keep_blank_values=False)
            filtered_query = [(k, v) for k, v in query_items if k.lower() not in TRACKING_QUERY_PARAMS]
            new_query = urlencode(filtered_query)
            clean_path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
            normalized = urlunparse((
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                clean_path,
                parsed.params,
                new_query,
                "",  # strip fragment
            ))
            return normalized
        except Exception:
            return url.strip()

    @classmethod
    def sanitize_content(cls, content: str, max_chars: int = 6000) -> str:
        """Sanitizes untrusted web content to neutralize prompt injections and strip excessive length."""
        if not content:
            return ""

        sanitized = content

        # 1. Neutralize prompt injection attempts
        for pattern, replacement_reason in PROMPT_INJECTION_PATTERNS:
            sanitized = re.sub(pattern, f"[FILTERED_PROMPT_INJECTION: {replacement_reason}]", sanitized)

        # 2. Strip HTML script and style tags if present
        sanitized = re.sub(r"(?i)<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>", "", sanitized)
        sanitized = re.sub(r"(?i)<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>", "", sanitized)

        # 3. Strip null bytes and non-printable control characters
        sanitized = sanitized.replace("\x00", "").replace("\r\n", "\n")

        # 4. Truncate to maximum characters
        if len(sanitized) > max_chars:
            sanitized = sanitized[:max_chars] + f"\n\n[Content truncated to {max_chars} characters for token safety]"

        return sanitized.strip()

    @classmethod
    def extract_version_hints(cls, text: str) -> Optional[str]:
        """Detects API or library version indications within documentation text."""
        if not text:
            return None

        # Look for patterns like "v2.1", "version 3", "2024-01-01", "v1"
        patterns = [
            r"\b(v\d+(?:\.\d+)?(?:\.[a-zA-Z0-9_-]+)?)\b",
            r"(?i)\bversion\s+(\d+(?:\.\d+)?)\b",
            r"\b(20\d{2}-\d{2}-\d{2})\b",
        ]
        for pat in patterns:
            match = re.search(pat, text)
            if match:
                return match.group(1)
        return None

    @classmethod
    def deduplicate_sources(cls, sources: List[ResearchSource]) -> List[ResearchSource]:
        """Deduplicates a list of research sources by normalized URL while preserving highest scores."""
        seen: Dict[str, ResearchSource] = {}
        for src in sources:
            norm_url = cls.normalize_url(src.url)
            if norm_url in seen:
                # If seen, keep the one with higher score or richer content
                existing = seen[norm_url]
                if src.score > existing.score or (not existing.content and src.content):
                    seen[norm_url] = src
            else:
                seen[norm_url] = src
        return list(seen.values())
