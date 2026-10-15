"""Unit tests for the secure n8n REST API client and status endpoint."""
import httpx
from httpx import ASGITransport
import pytest

from backend.app.services.n8n_client import (
    N8nClient,
    N8nConnectionState,
    N8nStatusResponse,
)
from backend.app.api.v1.integrations import get_n8n_client
from backend.app.main import app


@pytest.mark.asyncio
async def test_n8n_client_not_configured_when_key_is_missing():
    """Verify that empty or missing API keys immediately report not_configured."""
    client = N8nClient(
        base_url="http://localhost:5678",
        api_key="",
        http_client=httpx.AsyncClient(),
    )
    res = await client.check_connection()
    assert res.status == N8nConnectionState.NOT_CONFIGURED
    assert "not configured" in res.message.lower()
    await client.aclose()


@pytest.mark.asyncio
async def test_n8n_client_connected_valid_auth():
    """Verify successful connection and authentication against 200 OK n8n endpoint."""
    captured_headers = {}

    def mock_handler(request: httpx.Request):
        captured_headers.update(request.headers)
        assert request.url.path == "/api/v1/workflows"
        assert request.url.query == b"limit=1"
        return httpx.Response(200, json={"data": [{"id": "1", "name": "Sample Workflow"}]})

    mock_transport = httpx.MockTransport(mock_handler)
    mock_http = httpx.AsyncClient(transport=mock_transport)

    client = N8nClient(
        base_url="http://localhost:5678",
        api_key="valid_test_api_key_123",
        http_client=mock_http,
    )
    res = await client.check_connection()
    assert res.status == N8nConnectionState.CONNECTED
    assert "authenticated successfully" in res.message.lower()
    # Verify exact header name and value sent
    assert captured_headers.get("x-n8n-api-key") == "valid_test_api_key_123"
    await client.aclose()


@pytest.mark.asyncio
async def test_n8n_client_unauthorized_invalid_key():
    """Verify 401 response is safely mapped to unauthorized state."""
    def mock_handler(_request: httpx.Request):
        return httpx.Response(401, json={"message": "Unauthorized"})

    mock_transport = httpx.MockTransport(mock_handler)
    mock_http = httpx.AsyncClient(transport=mock_transport)

    client = N8nClient(
        base_url="http://localhost:5678",
        api_key="invalid_or_expired_key",
        http_client=mock_http,
    )
    res = await client.check_connection()
    assert res.status == N8nConnectionState.UNAUTHORIZED
    assert "invalid, expired" in res.message.lower()
    await client.aclose()


@pytest.mark.asyncio
async def test_n8n_client_forbidden_status():
    """Verify 403 response is mapped to unauthorized state."""
    def mock_handler(_request: httpx.Request):
        return httpx.Response(403, json={"message": "Forbidden"})

    mock_transport = httpx.MockTransport(mock_handler)
    mock_http = httpx.AsyncClient(transport=mock_transport)

    client = N8nClient(
        base_url="http://localhost:5678",
        api_key="forbidden_key",
        http_client=mock_http,
    )
    res = await client.check_connection()
    assert res.status == N8nConnectionState.UNAUTHORIZED
    await client.aclose()


@pytest.mark.asyncio
async def test_n8n_client_connection_refusal():
    """Verify connection refusal (e.g. stopped container) maps to unreachable."""
    def mock_handler(_request: httpx.Request):
        raise httpx.ConnectError("Connection refused to target host")

    mock_transport = httpx.MockTransport(mock_handler)
    mock_http = httpx.AsyncClient(transport=mock_transport)

    client = N8nClient(
        base_url="http://localhost:5678",
        api_key="any_key",
        http_client=mock_http,
    )
    res = await client.check_connection()
    assert res.status == N8nConnectionState.UNREACHABLE
    assert "could not connect" in res.message.lower()
    assert "http://localhost:5678" in res.message
    await client.aclose()


@pytest.mark.asyncio
async def test_n8n_client_timeout():
    """Verify request timeout maps to unreachable state."""
    def mock_handler(_request: httpx.Request):
        raise httpx.ReadTimeout("Request timed out waiting for server")

    mock_transport = httpx.MockTransport(mock_handler)
    mock_http = httpx.AsyncClient(transport=mock_transport)

    client = N8nClient(
        base_url="http://localhost:5678",
        api_key="any_key",
        http_client=mock_http,
    )
    res = await client.check_connection()
    assert res.status == N8nConnectionState.UNREACHABLE
    assert "timed out" in res.message.lower()
    await client.aclose()


@pytest.mark.asyncio
async def test_n8n_client_unexpected_http_status_500():
    """Verify 500 error maps to error status without exposing internal error trace."""
    def mock_handler(_request: httpx.Request):
        return httpx.Response(500, text="Internal Server Crash Dump")

    mock_transport = httpx.MockTransport(mock_handler)
    mock_http = httpx.AsyncClient(transport=mock_transport)

    client = N8nClient(
        base_url="http://localhost:5678",
        api_key="any_key",
        http_client=mock_http,
    )
    res = await client.check_connection()
    assert res.status == N8nConnectionState.ERROR
    assert "500" in res.message
    # Ensure raw server response text is NOT in user-facing message
    assert "Crash Dump" not in res.message
    await client.aclose()


@pytest.mark.asyncio
async def test_n8n_client_endpoint_not_found_404():
    """Verify 404 endpoint not found maps to error status."""
    def mock_handler(_request: httpx.Request):
        return httpx.Response(404, json={"message": "Not Found"})

    mock_transport = httpx.MockTransport(mock_handler)
    mock_http = httpx.AsyncClient(transport=mock_transport)

    client = N8nClient(
        base_url="http://localhost:5678",
        api_key="any_key",
        http_client=mock_http,
    )
    res = await client.check_connection()
    assert res.status == N8nConnectionState.ERROR
    assert "not found" in res.message.lower()
    await client.aclose()


def test_n8n_client_url_validation():
    """Verify URL validation blocks dangerous schemes and malformed URLs."""
    with pytest.raises(ValueError, match="Only http and https are allowed"):
        N8nClient(base_url="ftp://internal-server:21", api_key="test")

    with pytest.raises(ValueError, match="Only http and https are allowed"):
        N8nClient(base_url="file:///etc/passwd", api_key="test")

    with pytest.raises(ValueError, match="missing host"):
        N8nClient(base_url="http://", api_key="test")

    with pytest.raises(ValueError, match="cannot be empty"):
        N8nClient(base_url="", api_key="test")


@pytest.mark.asyncio
async def test_secret_redaction_in_messages():
    """Verify API keys are never leaked into messages or string representations."""
    secret_key = "super_secret_high_entropy_api_token_abc987654321"

    def mock_handler(_request: httpx.Request):
        raise RuntimeError(f"Simulated internal bug containing {secret_key}")

    mock_transport = httpx.MockTransport(mock_handler)
    mock_http = httpx.AsyncClient(transport=mock_transport)

    client = N8nClient(
        base_url="http://localhost:5678",
        api_key=secret_key,
        http_client=mock_http,
    )
    res = await client.check_connection()
    assert res.status == N8nConnectionState.ERROR
    # Secret must never be leaked
    assert secret_key not in res.message
    assert "[REDACTED]" not in res.message  # General message used instead of raw trace
    await client.aclose()


@pytest.mark.asyncio
async def test_fastapi_status_endpoint():
    """Verify GET /api/v1/integrations/n8n/status returns sanitized response."""
    def mock_handler(_request: httpx.Request):
        return httpx.Response(200, json={"data": []})

    mock_transport = httpx.MockTransport(mock_handler)
    mock_http = httpx.AsyncClient(transport=mock_transport)
    test_client = N8nClient(
        base_url="http://localhost:5678",
        api_key="mock_key",
        http_client=mock_http,
    )

    async def mock_get_client():
        yield test_client

    app.dependency_overrides[get_n8n_client] = mock_get_client

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/integrations/n8n/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert "authenticated successfully" in data["message"].lower()

    app.dependency_overrides.clear()
    await test_client.aclose()


@pytest.mark.asyncio
async def test_async_context_manager():
    """Verify N8nClient functions properly with async with context manager."""
    async with N8nClient(base_url="http://localhost:5678", api_key="") as client:
        res = await client.check_connection()
        assert res.status == N8nConnectionState.NOT_CONFIGURED
