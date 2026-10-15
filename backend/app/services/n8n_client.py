"""Secure, read-only n8n REST API client.

This module provides authenticated connectivity checking for self-hosted n8n instances.
It enforces strict secret isolation: raw API keys are never logged, returned, or leaked.
"""
from enum import Enum
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import httpx
from pydantic import BaseModel, Field

from backend.app.config import N8NSettings

logger = logging.getLogger(__name__)


class N8nConnectionState(str, Enum):
    """Sanitized states for n8n instance connection status."""

    CONNECTED = "connected"
    NOT_CONFIGURED = "not_configured"
    UNAUTHORIZED = "unauthorized"
    UNREACHABLE = "unreachable"
    ERROR = "error"


class N8nStatusResponse(BaseModel):
    """Sanitized response model reporting n8n instance connection status."""

    status: N8nConnectionState = Field(
        description="Categorized connection and authentication status."
    )
    message: str = Field(
        description="Safe human-readable summary without secrets or raw errors."
    )


class N8nWorkflowCreationResult(BaseModel):
    """Result of successfully creating an inactive workflow in n8n."""

    workflow_id: str
    workflow_name: str
    is_active: bool = False
    workflow_url: Optional[str] = None
    created_at: Optional[str] = None


class N8nDeploymentError(Exception):
    """Raised when n8n rejects workflow creation with a sanitized error."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class N8nDeploymentTimeoutError(N8nDeploymentError):
    """Raised when n8n creation times out, leaving deployment outcome uncertain."""

    def __init__(self, message: str):
        super().__init__(message, status_code=504)
        self.is_uncertain = True


class N8nClient:
    """Asynchronous read-only client for checking n8n instance status."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        settings = N8NSettings()
        raw_url = base_url if base_url is not None else settings.N8N_BASE_URL
        self.base_url = self._validate_and_normalize_url(raw_url)
        self.api_key = api_key if api_key is not None else settings.N8N_API_KEY
        self.timeout = timeout if timeout is not None else settings.N8N_TIMEOUT_SEC

        self._external_client = http_client is not None
        self._http_client = http_client or httpx.AsyncClient(timeout=self.timeout)

    @staticmethod
    def _validate_and_normalize_url(url: str) -> str:
        """Validate URL to prevent arbitrary protocols or SSRF."""
        clean = (url or "").strip().rstrip("/")
        if not clean:
            raise ValueError("n8n base URL cannot be empty.")
        parsed = urlparse(clean)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid URL scheme '{parsed.scheme}'. Only http and https are allowed.")
        if not parsed.netloc:
            raise ValueError("Invalid URL: missing host or network location.")
        return clean

    def _sanitize_message(self, text: str) -> str:
        """Ensure no secrets or authorization headers leak in error text."""
        if not text:
            return ""
        sanitized = text
        if self.api_key and self.api_key.strip():
            sanitized = sanitized.replace(self.api_key.strip(), "[REDACTED]")
        return sanitized

    async def check_connection(self) -> N8nStatusResponse:
        """Test read-only connectivity and authentication to the n8n REST API.

        Uses GET /api/v1/workflows?limit=1 with X-N8N-API-KEY header to verify
        real REST API authentication rather than just web server accessibility.
        """
        # 1. Verify configuration presence
        if not self.api_key or not self.api_key.strip():
            logger.info("n8n connection check: N8N_API_KEY is not configured.")
            return N8nStatusResponse(
                status=N8nConnectionState.NOT_CONFIGURED,
                message="n8n API key is not configured in backend environment.",
            )

        headers = {
            "X-N8N-API-KEY": self.api_key.strip(),
            "Accept": "application/json",
            "User-Agent": "n8n-workflow-ai-studio",
        }
        endpoint = f"{self.base_url}/api/v1/workflows?limit=1"

        try:
            response = await self._http_client.get(endpoint, headers=headers)

            if response.status_code == 200:
                logger.info("n8n connection check: Connected and authenticated successfully.")
                return N8nStatusResponse(
                    status=N8nConnectionState.CONNECTED,
                    message="Connected and authenticated successfully with n8n instance.",
                )

            if response.status_code in (401, 403):
                logger.warning("n8n connection check: Unauthorized (status %s).", response.status_code)
                return N8nStatusResponse(
                    status=N8nConnectionState.UNAUTHORIZED,
                    message="n8n API key is invalid, expired, or lacks permission.",
                )

            if response.status_code == 404:
                logger.warning("n8n connection check: Endpoint not found (404).")
                return N8nStatusResponse(
                    status=N8nConnectionState.ERROR,
                    message="n8n REST API endpoint was not found at configured URL.",
                )

            logger.error("n8n connection check: Upstream returned HTTP %s.", response.status_code)
            return N8nStatusResponse(
                status=N8nConnectionState.ERROR,
                message=f"n8n instance returned unexpected HTTP status {response.status_code}.",
            )

        except (httpx.ConnectError, httpx.NetworkError):
            logger.warning("n8n connection check: ConnectError at %s", self.base_url)
            return N8nStatusResponse(
                status=N8nConnectionState.UNREACHABLE,
                message=f"Could not connect to n8n instance at {self.base_url}. Ensure container is running.",
            )

        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.TimeoutException):
            logger.warning("n8n connection check: Request timed out at %s", self.base_url)
            return N8nStatusResponse(
                status=N8nConnectionState.UNREACHABLE,
                message=f"Connection to n8n instance at {self.base_url} timed out.",
            )

        except Exception as e:
            logger.error("n8n connection check error: %s", type(e).__name__)
            return N8nStatusResponse(
                status=N8nConnectionState.ERROR,
                message="An unexpected error occurred while communicating with n8n instance.",
            )

    async def get_credentials(self) -> List[dict]:
        """Fetch credential metadata from n8n REST API (GET /api/v1/credentials).

        Enforces secret isolation: extracts only safe metadata ('id', 'name', 'type', 'createdAt', 'updatedAt').
        Never retrieves or exposes secrets or sensitive credentials data.
        Returns empty list if n8n is not configured, unreachable, or unauthorized.
        """
        if not self.api_key or not self.api_key.strip():
            return []

        headers = {
            "X-N8N-API-KEY": self.api_key.strip(),
            "Accept": "application/json",
            "User-Agent": "n8n-workflow-ai-studio",
        }
        endpoint = f"{self.base_url}/api/v1/credentials"

        try:
            response = await self._http_client.get(endpoint, headers=headers)
            if response.status_code == 200:
                data = response.json()
                raw_list = data.get("data") if isinstance(data, dict) and "data" in data else data
                if isinstance(raw_list, list):
                    sanitized = []
                    for c in raw_list:
                        if isinstance(c, dict) and "id" in c and "type" in c:
                            sanitized.append({
                                "id": str(c["id"]),
                                "name": str(c.get("name") or c["id"]),
                                "type": str(c["type"]),
                                "created_at": c.get("createdAt"),
                                "updated_at": c.get("updatedAt"),
                            })
                    return sanitized
            return []
        except Exception as exc:
            logger.warning("Failed to fetch n8n credentials: %s", self._sanitize_message(str(exc)))
            return []

    async def create_workflow(self, workflow_data: dict) -> N8nWorkflowCreationResult:
        """Create an inactive workflow in the target n8n instance via REST API.

        Enforces safety policies:
        - Workflows are strictly created in an inactive state (active=False).
        - Explicit human approval must precede this call.
        - Secrets and authorization headers are never logged or leaked.
        - Timeouts raise N8nDeploymentTimeoutError indicating an uncertain outcome.
        """
        if not self.api_key or not self.api_key.strip():
            raise N8nDeploymentError("n8n API key is not configured in backend environment.", status_code=401)

        headers = {
            "X-N8N-API-KEY": self.api_key.strip(),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "n8n-workflow-ai-studio",
        }
        endpoint = f"{self.base_url}/api/v1/workflows"

        # Construct strictly inactive payload
        wf_name = workflow_data.get("name") or "AI Generated Workflow"
        payload = {
            "name": wf_name,
            "nodes": workflow_data.get("nodes", []),
            "connections": workflow_data.get("connections", {}),
            "settings": workflow_data.get("settings", {"executionOrder": "v1"}),
            "active": False,
        }

        try:
            response = await self._http_client.post(endpoint, json=payload, headers=headers)

            if response.status_code in (200, 201):
                data = response.json()
                # Handle root object or nested 'data' key
                wf_obj = data.get("data") if isinstance(data.get("data"), dict) else data
                wf_id = str(wf_obj.get("id") or "")
                if not wf_id:
                    raise N8nDeploymentError("n8n responded with 200/201 but omitted the workflow ID.")

                wf_url = f"{self.base_url}/workflow/{wf_id}"
                logger.info("Successfully created workflow '%s' (ID: %s) in n8n (inactive).", wf_name, wf_id)
                return N8nWorkflowCreationResult(
                    workflow_id=wf_id,
                    workflow_name=wf_obj.get("name", wf_name),
                    is_active=bool(wf_obj.get("active", False)),
                    workflow_url=wf_url,
                    created_at=wf_obj.get("createdAt"),
                )

            if response.status_code in (401, 403):
                raise N8nDeploymentError(
                    "Unauthorized: n8n API key is invalid, expired, or lacks permission to create workflows.",
                    status_code=response.status_code,
                )

            if response.status_code == 400:
                try:
                    err_json = response.json()
                    err_msg = err_json.get("message") or err_json.get("detail") or "Invalid workflow payload."
                except Exception:
                    err_msg = response.text or "Invalid workflow payload."
                clean_msg = self._sanitize_message(err_msg)
                raise N8nDeploymentError(f"n8n rejected workflow: {clean_msg}", status_code=400)

            raise N8nDeploymentError(
                f"n8n returned unexpected HTTP status {response.status_code} during workflow creation.",
                status_code=response.status_code,
            )

        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.TimeoutException) as te:
            logger.warning("n8n workflow creation timed out: %s", str(te))
            raise N8nDeploymentTimeoutError(
                f"Request to create workflow timed out after {self.timeout}s. "
                "The workflow creation outcome is uncertain. Check n8n before retrying to prevent duplicate workflows."
            ) from te

        except (httpx.ConnectError, httpx.NetworkError) as ne:
            logger.warning("n8n network error: %s", str(ne))
            raise N8nDeploymentError(
                f"Could not connect to n8n instance at {self.base_url}. Ensure container is running.",
                status_code=503,
            ) from ne

        except N8nDeploymentError:
            raise

        except Exception as e:
            clean_err = self._sanitize_message(str(e))
            logger.error("Unexpected error during workflow deployment: %s", clean_err)
            raise N8nDeploymentError(f"Failed to create workflow in n8n: {clean_err}") from e

    async def aclose(self) -> None:
        """Close underlying HTTP client if created internally."""
        if not self._external_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def __aenter__(self) -> "N8nClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.aclose()
