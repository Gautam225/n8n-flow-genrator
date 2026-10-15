"""Security package exposing sanitization, authentication, and defensive middleware."""
from backend.app.security.sanitizer import SecretSanitizer, sanitize_secrets
from backend.app.security.auth import (
    UserContext,
    get_current_user,
    verify_conversation_ownership,
)
from backend.app.security.middleware import (
    PayloadSizeLimitMiddleware,
    RateLimiterMiddleware,
    SecurityHeadersMiddleware,
)

__all__ = [
    "SecretSanitizer",
    "sanitize_secrets",
    "UserContext",
    "get_current_user",
    "verify_conversation_ownership",
    "PayloadSizeLimitMiddleware",
    "RateLimiterMiddleware",
    "SecurityHeadersMiddleware",
]
