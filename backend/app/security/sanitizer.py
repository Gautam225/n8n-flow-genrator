"""Deterministic secret scrubbing and sanitization service.

Detects and redacts tokens, credentials, connection passwords, and private keys
from outgoing logs, diagnostic endpoints, error traces, and LLM prompts.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Pattern, Union

# Common secret regex patterns
REDACTION_PATTERNS: List[tuple[str, Pattern[str]]] = [
    # OpenRouter API Keys (e.g. sk-or-v1-...)
    ("OPENROUTER_KEY", re.compile(r"sk-or-v1-[A-Za-z0-9_\-]{16,}", re.IGNORECASE)),
    # Groq API Keys (e.g. gsk_...)
    ("GROQ_KEY", re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b")),
    # GitHub Personal Access Tokens
    ("GITHUB_PAT", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b")),
    # AWS Access Key ID
    ("AWS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # Standard Bearer Tokens
    ("BEARER_TOKEN", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]{15,}=*\b")),
    # Standard Basic Auth Headers
    ("BASIC_AUTH_HEADER", re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/=]{10,}\b")),
    # Standalone JWT Tokens
    ("JWT_TOKEN", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    # Generic URL credentials: scheme://user:password@host (http, https, postgres, redis, mysql, etc.)
    (
        "URL_CREDENTIALS",
        re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]+://[^:/\s]+:)([^@/\s]+)(@)", re.IGNORECASE),
    ),
    # PEM Private Keys
    (
        "PRIVATE_KEY",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    # Telegram Bot Token (e.g. 123456789:ABCdefGhIjkLmNoPqRsTuVwXyZ12345678)
    ("TELEGRAM_BOT_TOKEN", re.compile(r"\b\d{8,11}:[A-Za-z0-9_-]{34,36}\b")),
    # Explicit secret assignments: api_key=..., password=..., secret=...
    (
        "EXPLICIT_SECRET",
        re.compile(
            r"""(?i)(["']?(?:api[_-]?key|password|secret|auth[_-]?token|access[_-]?token|private[_-]?key|bot[_-]?token)["']?\s*[:=]\s*["'])([^"'}\s]{8,})(["'])"""
        ),
    ),
]



class SecretSanitizer:
    """Provides recursive secret scrubbing for strings, dictionaries, lists, and exception messages."""

    REDACTED_LABEL: str = "[REDACTED]"

    def __init__(self, explicit_secrets: Optional[List[str]] = None):
        """Initializes sanitizer with optional dynamic runtime secrets to scrub."""
        self.explicit_secrets = [s for s in (explicit_secrets or []) if s]

    def sanitize(self, text: str) -> str:
        """Sanitizes text against standard patterns and dynamic explicit secrets."""
        res = self.sanitize_text(text)
        for s in self.explicit_secrets:
            if s:
                res = res.replace(s, self.REDACTED_LABEL)
        return res

    @classmethod
    def sanitize_text(cls, text: str) -> str:
        """Scrubs recognized secret patterns from a string."""
        if not text:
            return text

        result = text
        for name, pattern in REDACTION_PATTERNS:
            if name in ("DB_PASSWORD", "URL_CREDENTIALS"):
                result = pattern.sub(r"\1***\3", result)
            elif name == "EXPLICIT_SECRET":
                result = pattern.sub(rf"\1{cls.REDACTED_LABEL}\3", result)
            else:
                result = pattern.sub(cls.REDACTED_LABEL, result)

        return result

    @classmethod
    def sanitize_obj(cls, obj: Any) -> Any:
        """Recursively sanitizes dictionaries, lists, and strings."""
        if isinstance(obj, str):
            return cls.sanitize_text(obj)
        elif isinstance(obj, dict):
            clean_dict: Dict[str, Any] = {}
            for k, v in obj.items():
                # If key explicitly indicates secret, mask value if it's a string
                k_lower = str(k).lower()
                if any(sec in k_lower for sec in ("password", "secret", "token", "apikey", "api_key", "private_key")):
                    if isinstance(v, str):
                        clean_dict[k] = cls.REDACTED_LABEL
                    elif isinstance(v, (dict, list)):
                        clean_dict[k] = cls.sanitize_obj(v)
                    else:
                        clean_dict[k] = cls.REDACTED_LABEL
                else:
                    clean_dict[k] = cls.sanitize_obj(v)
            return clean_dict
        elif isinstance(obj, list):
            return [cls.sanitize_obj(item) for item in obj]
        elif isinstance(obj, tuple):
            return tuple(cls.sanitize_obj(item) for item in obj)
        return obj

    # Convenient alias
    sanitize_data = sanitize_obj


def sanitize_secrets(value: Union[str, Dict[str, Any], List[Any], Any]) -> Any:
    """Convenience functional wrapper for secret sanitization."""
    if isinstance(value, str):
        return SecretSanitizer.sanitize_text(value)
    return SecretSanitizer.sanitize_obj(value)
