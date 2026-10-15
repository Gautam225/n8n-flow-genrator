"""Authentication and user-isolation authorization mechanisms.

Supports local trusted development mode, optional pre-shared studio API key
validation, and per-user conversation/draft isolation.
"""
from dataclasses import dataclass
import re
from typing import Any, Optional

from fastapi import Header, HTTPException, Request, WebSocket, status

from backend.app.config import AppSettings

USER_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]{1,64}$")


@dataclass(frozen=True)
class UserContext:
    """Authenticated user context for the request session."""
    user_id: str
    is_authenticated: bool
    auth_method: str  # "local_trust" | "api_key" | "user_header"


def get_current_user(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> UserContext:
    """FastAPI dependency resolving and validating the current user context.
    
    In local development when STUDIO_API_KEY is unset, requests from loopback
    are trusted and assigned 'local_user' (or the client's X-User-Id).
    When STUDIO_API_KEY is configured, valid API key credentials are mandatory.
    """
    settings = AppSettings()

    # 1. Check API Key requirement if configured or enforced
    if settings.STUDIO_API_KEY or getattr(settings, "AUTH_ENFORCED", False):
        configured_key = (settings.STUDIO_API_KEY or "").strip()
        if not configured_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication is enforced but STUDIO_API_KEY is not configured.",
            )
        provided_token = None

        if x_api_key:
            provided_token = x_api_key.strip()
        elif authorization:
            parts = authorization.strip().split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                provided_token = parts[1]
            elif len(parts) == 1:
                provided_token = parts[0]

        if not provided_token or provided_token != configured_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing studio authentication credentials.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        auth_method = "api_key"
    else:
        # Local trust mode: restrict strictly to loopback callers
        client_host = request.client.host if request.client else "127.0.0.1"
        if client_host not in ("127.0.0.1", "::1", "localhost", "testclient"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Remote access prohibited without configured STUDIO_API_KEY.",
            )
        auth_method = "local_trust"

    # 2. Resolve User Identifier for multi-user isolation
    if x_user_id and x_user_id.strip():
        clean_user_id = x_user_id.strip()
        if not USER_ID_REGEX.match(clean_user_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-User-Id format. Must be 1-64 characters alphanumeric, hyphen, underscore, or period.",
            )
        resolved_user_id = clean_user_id
        if auth_method == "local_trust":
            auth_method = "user_header"
    else:
        resolved_user_id = "local_user"

    return UserContext(
        user_id=resolved_user_id,
        is_authenticated=True,
        auth_method=auth_method,
    )


def verify_conversation_ownership(conversation: Any, user: UserContext) -> None:
    """Verifies that the resolved user is authorized to access the conversation entity."""
    metadata = getattr(conversation, "metadata_json", None) or {}
    owner_id = metadata.get("user_id")

    # If conversation has an explicit owner, strictly enforce match
    if owner_id and owner_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: You do not have permission to access conversation '{getattr(conversation, 'id', '')}'.",
        )


async def authenticate_websocket(websocket: WebSocket) -> UserContext:
    """Authenticates an incoming WebSocket connection via query parameters or headers."""
    settings = AppSettings()
    query_params = dict(websocket.query_params)
    headers = websocket.headers

    token = (
        query_params.get("token")
        or query_params.get("api_key")
        or headers.get("x-api-key")
        or headers.get("authorization")
    )
    if token and token.lower().startswith("bearer "):
        token = token[7:].strip()

    if settings.STUDIO_API_KEY or getattr(settings, "AUTH_ENFORCED", False):
        configured_key = (settings.STUDIO_API_KEY or "").strip()
        if not token or token != configured_key:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing studio authentication credentials.",
            )
        auth_method = "api_key"
    else:
        client_host = websocket.client.host if websocket.client else "127.0.0.1"
        if client_host not in ("127.0.0.1", "::1", "localhost", "testclient"):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Remote access prohibited without configured STUDIO_API_KEY.",
            )
        auth_method = "local_trust"

    user_id = query_params.get("user_id") or headers.get("x-user-id") or "local_user"
    if user_id and not USER_ID_REGEX.match(user_id):
        user_id = "local_user"

    return UserContext(
        user_id=user_id,
        is_authenticated=True,
        auth_method=auth_method,
    )

