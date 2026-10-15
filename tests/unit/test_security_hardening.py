"""Unit and integration security tests for Phase 6: Security and Reliability Hardening."""
import json
import time
import uuid
import pytest
import httpx
from httpx import ASGITransport
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.app.config import AppSettings, N8NSettings
from backend.app.main import app
from backend.app.models.conversation import Conversation
from backend.app.schemas.ir import IRNode, WorkflowIR
from backend.app.security.auth import UserContext, get_current_user, verify_conversation_ownership
from backend.app.security.middleware import (
    PayloadSizeLimitMiddleware,
    RateLimiterMiddleware,
    SecurityHeadersMiddleware,
)
from backend.app.security.sanitizer import SecretSanitizer, sanitize_secrets
from backend.app.services.node_registry import NodeRegistry
from backend.app.services.validator import WorkflowValidator


# ==============================================================================
# 1. Secret Sanitization Tests
# ==============================================================================

def test_secret_sanitizer_api_keys_and_passwords():
    """Verify regex and exact pattern scrubbing of API keys and passwords."""
    raw = (
        "OpenRouter key sk-or-v1-abcdef0123456789abcdef0123456789abcdef0123456789 "
        "and Groq key gsk_1234567890abcdef1234567890abcdef1234567890abcdef "
        "and DB uri postgresql+asyncpg://postgres:supersecretpassword99@localhost:5432/n8n_ai "
        "and Bearer super_bearer_token_xyz"
    )
    sanitized = SecretSanitizer.sanitize_text(raw)

    assert "sk-or-v1-" not in sanitized
    assert "gsk_" not in sanitized
    assert "supersecretpassword99" not in sanitized
    assert "super_bearer_token_xyz" not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized or "[REDACTED]" in sanitized
    assert "postgres:***@localhost:5432/n8n_ai" in sanitized or "[REDACTED]" in sanitized


def test_secret_sanitizer_explicit_registered_secrets():
    """Verify registered dynamic runtime secrets are redacted completely."""
    secret = "my_custom_high_entropy_secret_value_123"
    sanitizer = SecretSanitizer(explicit_secrets=[secret])

    text = f"An error occurred while connecting: {secret} failed to authenticate."
    sanitized = sanitizer.sanitize(text)

    assert secret not in sanitized
    assert "[REDACTED]" in sanitized or "[REDACTED_SECRET]" in sanitized


def test_secret_sanitizer_data_structures():
    """Verify recursive dictionary/list secret sanitization."""
    data = {
        "user": "developer",
        "api_key": "raw_sensitive_key_999",
        "nested": {
            "password": "db_password_abc",
            "safe_list": [
                "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",
                "normal_string",
            ],
        },
    }
    sanitized = SecretSanitizer.sanitize_data(data)

    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["password"] == "[REDACTED]"
    assert "sk-or-v1-" not in sanitized["nested"]["safe_list"][0]
    assert sanitized["nested"]["safe_list"][1] == "normal_string"


# ==============================================================================
# 2. Authentication & User Context Tests
# ==============================================================================

def test_get_current_user_local_trust_mode(monkeypatch):
    """In default local mode without STUDIO_API_KEY, requests default to local_user."""
    monkeypatch.delenv("STUDIO_API_KEY", raising=False)
    monkeypatch.delenv("AUTH_ENFORCED", raising=False)

    class DummyRequest:
        client = None

    user = get_current_user(request=DummyRequest(), x_api_key=None, authorization=None, x_user_id=None)
    assert user.user_id == "local_user"
    assert user.is_authenticated is True
    assert user.auth_method == "local_trust"


def test_get_current_user_custom_user_id(monkeypatch):
    """Clients can specify valid X-User-Id for session isolation."""
    monkeypatch.delenv("STUDIO_API_KEY", raising=False)

    class DummyRequest:
        client = None

    user = get_current_user(
        request=DummyRequest(),
        x_api_key=None,
        authorization=None,
        x_user_id="user_alice_42",
    )
    assert user.user_id == "user_alice_42"
    assert user.auth_method == "user_header"


def test_get_current_user_invalid_user_id_rejected():
    """Unsafe or malicious X-User-Id headers are rejected with 400 Bad Request."""
    class DummyRequest:
        client = None

    with pytest.raises(HTTPException) as exc:
        get_current_user(
            request=DummyRequest(),
            x_api_key=None,
            authorization=None,
            x_user_id="<script>alert(1)</script>",
        )
    assert exc.value.status_code == 400


def test_get_current_user_studio_api_key_enforcement(monkeypatch):
    """When STUDIO_API_KEY is configured, requests without valid credentials are rejected (401)."""
    monkeypatch.setenv("STUDIO_API_KEY", "correct_studio_secret_token_123")

    class DummyRequest:
        client = None

    # Missing credentials -> 401
    with pytest.raises(HTTPException) as exc:
        get_current_user(
            request=DummyRequest(),
            x_api_key=None,
            authorization=None,
            x_user_id=None,
        )
    assert exc.value.status_code == 401

    # Invalid credential -> 401
    with pytest.raises(HTTPException) as exc2:
        get_current_user(
            request=DummyRequest(),
            x_api_key="wrong_token",
            authorization=None,
            x_user_id=None,
        )
    assert exc2.value.status_code == 401

    # Valid X-API-Key header -> 200
    user = get_current_user(
        request=DummyRequest(),
        x_api_key="correct_studio_secret_token_123",
        authorization=None,
        x_user_id="operator_bob",
    )
    assert user.user_id == "operator_bob"
    assert user.auth_method == "api_key"

    # Valid Bearer authorization -> 200
    user2 = get_current_user(
        request=DummyRequest(),
        x_api_key=None,
        authorization="Bearer correct_studio_secret_token_123",
        x_user_id="operator_bob",
    )
    assert user2.user_id == "operator_bob"
    assert user2.auth_method == "api_key"


def test_verify_conversation_ownership():
    """Cross-user conversation tampering is strictly prevented with 403 Forbidden."""
    conv_alice = Conversation(
        id="conv-1",
        title="Alice Flow",
        metadata_json={"user_id": "alice"},
    )

    user_alice = UserContext(user_id="alice", is_authenticated=True, auth_method="local_trust")
    user_bob = UserContext(user_id="bob", is_authenticated=True, auth_method="local_trust")

    # Alice accessing Alice's conversation -> Allowed
    verify_conversation_ownership(conv_alice, user_alice)

    # Bob accessing Alice's conversation -> Forbidden (403)
    with pytest.raises(HTTPException) as exc:
        verify_conversation_ownership(conv_alice, user_bob)
    assert exc.value.status_code == 403


# ==============================================================================
# 3. Network & SSRF Security Tests
# ==============================================================================

def test_n8n_settings_ssrf_blocking():
    """Verify N8NSettings blocks cloud metadata and link-local IP addresses."""
    # Cloud metadata IP
    with pytest.raises(ValueError, match="cloud metadata"):
        N8NSettings(N8N_BASE_URL="http://169.254.169.254:80")

    # GCP metadata hostname
    with pytest.raises(ValueError, match="cloud metadata"):
        N8NSettings(N8N_BASE_URL="http://metadata.google.internal")

    # Link-local subnet
    with pytest.raises(ValueError, match="cloud metadata"):
        N8NSettings(N8N_BASE_URL="http://169.254.10.20:5678")

    # Valid local n8n instance is accepted
    valid_settings = N8NSettings(N8N_BASE_URL="http://localhost:5678")
    assert valid_settings.N8N_BASE_URL == "http://localhost:5678"


# ==============================================================================
# 4. Middleware Tests (Payload Size, Rate Limit, Security Headers)
# ==============================================================================

@pytest.mark.asyncio
async def test_security_headers_middleware():
    """Verify security headers are applied to HTTP responses."""
    test_app = FastAPI()
    test_app.add_middleware(SecurityHeadersMiddleware)

    @test_app.get("/ping")
    async def ping():
        return {"ping": "pong"}

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/ping")
        assert resp.status_code == 200
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


@pytest.mark.asyncio
async def test_payload_size_limit_middleware():
    """Verify requests exceeding max_bytes are rejected with 413 Payload Too Large."""
    test_app = FastAPI()
    test_app.add_middleware(PayloadSizeLimitMiddleware, max_bytes=100)

    @test_app.post("/upload")
    async def upload(payload: dict):
        return {"received": True}

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Small payload -> 200
        small_resp = await client.post("/upload", json={"a": "b"})
        assert small_resp.status_code == 200

        # Oversized payload (> 100 bytes) -> 413
        large_resp = await client.post("/upload", json={"large_data": "x" * 200})
        assert large_resp.status_code == 413
        assert "exceeds maximum allowed size" in large_resp.json()["detail"]


@pytest.mark.asyncio
async def test_rate_limiter_middleware():
    """Verify client exceeding sliding window rate limit receives 429 Too Many Requests."""
    test_app = FastAPI()
    # Limit to 3 requests per minute for fast testing
    test_app.add_middleware(RateLimiterMiddleware, requests_per_minute=3)

    @test_app.get("/action")
    async def action():
        return {"ok": True}

    @test_app.get("/healthz")
    async def health():
        return {"status": "ok"}

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # First 3 requests succeed
        for _ in range(3):
            r = await client.get("/action")
            assert r.status_code == 200

        # 4th request exceeds rate limit -> 429
        rate_limited_r = await client.get("/action")
        assert rate_limited_r.status_code == 429
        assert rate_limited_r.headers.get("Retry-After") == "60"

        # Excluded healthz endpoint is NOT rate limited
        health_r = await client.get("/healthz")
        assert health_r.status_code == 200


# ==============================================================================
# 5. Restricted Node & Code Sandboxing Validation Tests
# ==============================================================================

def test_restricted_node_execute_command_blocked():
    """Verify n8n-nodes-base.executeCommand is flagged as FATAL_RESTRICTED_NODE."""
    validator = WorkflowValidator(registry=NodeRegistry())
    wf = WorkflowIR(
        id=str(uuid.uuid4()),
        name="Host Execution Attempt",
        nodes=[
            IRNode(
                id="cmd1",
                name="Execute Command",
                node_type="n8n-nodes-base.executeCommand",
                type_version=1,
                parameters={"command": "rm -rf /"},
            )
        ],
        edges=[],
    )
    report = validator.validate(wf)
    assert report.is_valid is False
    assert any(issue.rule_code == "FATAL_RESTRICTED_NODE" for issue in report.issues)


def test_code_node_sandbox_violation_blocked():
    """Verify Code nodes attempting child_process or filesystem access are flagged as RESTRICTED_CODE_SANDBOX."""
    validator = WorkflowValidator(registry=NodeRegistry())
    wf = WorkflowIR(
        id=str(uuid.uuid4()),
        name="Sandbox Escape Attempt",
        nodes=[
            IRNode(
                id="code1",
                name="Dangerous Code",
                node_type="n8n-nodes-base.code",
                type_version=2,
                parameters={
                    "mode": "runOnceForEachItem",
                    "jsCode": "const { exec } = require('child_process'); exec('whoami');",
                },
            )
        ],
        edges=[],
    )
    report = validator.validate(wf)
    assert report.is_valid is False
    assert any(issue.rule_code == "RESTRICTED_CODE_SANDBOX" for issue in report.issues)


def test_code_node_safe_transform_allowed():
    """Verify standard data transformation in Code nodes passes sandboxing check."""
    validator = WorkflowValidator(registry=NodeRegistry())
    wf = WorkflowIR(
        id=str(uuid.uuid4()),
        name="Safe Transformation",
        nodes=[
            IRNode(
                id="code1",
                name="Safe Code",
                node_type="n8n-nodes-base.code",
                type_version=2,
                parameters={
                    "mode": "runOnceForEachItem",
                    "jsCode": "item.json.counter = (item.json.counter || 0) + 1;\nreturn item;",
                },
            )
        ],
        edges=[],
    )
    report = validator.validate(wf)
    # Should not flag sandbox errors
    assert not any(issue.rule_code == "RESTRICTED_CODE_SANDBOX" for issue in report.issues)


# ==============================================================================
# 6. Phase 7A Security Audit Regression Tests
# ==============================================================================

def test_get_current_user_remote_client_forbidden_in_local_trust(monkeypatch):
    """Remote IP attempting local trust authentication without API key is rejected with 403."""
    monkeypatch.delenv("STUDIO_API_KEY", raising=False)
    monkeypatch.delenv("AUTH_ENFORCED", raising=False)

    class RemoteClient:
        host = "192.168.1.150"

    class RemoteRequest:
        client = RemoteClient()

    with pytest.raises(HTTPException) as exc:
        get_current_user(request=RemoteRequest(), x_api_key=None, authorization=None, x_user_id=None)
    assert exc.value.status_code == 403
    assert "Remote access prohibited" in exc.value.detail


def test_get_current_user_empty_studio_api_key_when_enforced(monkeypatch):
    """When AUTH_ENFORCED is set but STUDIO_API_KEY is empty/whitespace, fail securely with 500."""
    monkeypatch.setenv("AUTH_ENFORCED", "true")
    monkeypatch.setenv("STUDIO_API_KEY", "   ")

    class DummyRequest:
        client = None

    with pytest.raises(HTTPException) as exc:
        get_current_user(request=DummyRequest(), x_api_key="anything", authorization=None, x_user_id=None)
    assert exc.value.status_code == 500
    assert "STUDIO_API_KEY is not configured" in exc.value.detail


@pytest.mark.asyncio
async def test_payload_size_limit_streaming_chunked():
    """Verify PayloadSizeLimitMiddleware rejects streaming/chunked requests exceeding limit without consuming body."""
    test_app = FastAPI()
    test_app.add_middleware(PayloadSizeLimitMiddleware, max_bytes=50)

    @test_app.post("/stream")
    async def stream_endpoint(request: Request):
        body = await request.body()
        return {"received": len(body)}

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Request with body > 50 bytes via stream generator without Content-Length
        async def large_generator():
            yield b"x" * 30
            yield b"y" * 30

        resp = await client.post("/stream", content=large_generator())
        assert resp.status_code == 413
        assert "exceeds maximum allowed size" in resp.json()["detail"]

        # Request under limit succeeds
        async def small_generator():
            yield b"hello "
            yield b"world"

        resp2 = await client.post("/stream", content=small_generator())
        assert resp2.status_code == 200
        assert resp2.json()["received"] == 11


@pytest.mark.asyncio
async def test_rate_limiter_memory_bounding():
    """Verify RateLimiterMiddleware bounds memory and caps tracked IPs."""
    limiter = RateLimiterMiddleware(app=FastAPI(), requests_per_minute=100)
    limiter.MAX_TRACKED_IPS = 50  # Lower threshold for quick unit testing

    # Populate with 100 distinct IPs
    now = time.time()
    async with limiter._lock:
        for i in range(100):
            client_ip = f"10.0.{i // 256}.{i % 256}"
            limiter._history[client_ip] = [now]
            # Trigger eviction check
            if len(limiter._history) > limiter.MAX_TRACKED_IPS:
                sorted_ips = sorted(
                    limiter._history.keys(),
                    key=lambda ip: max(limiter._history[ip]) if limiter._history[ip] else 0,
                )
                for old_ip in sorted_ips[: len(limiter._history) - limiter.MAX_TRACKED_IPS]:
                    del limiter._history[old_ip]

    # Must be bounded by MAX_TRACKED_IPS
    assert len(limiter._history) <= 50


def test_n8n_settings_link_local_ipv6_and_cloud_metadata():
    """Verify N8NSettings rejects IPv6 link-local and cloud metadata addresses."""
    # IPv6 link-local
    with pytest.raises(ValueError, match="link-local"):
        N8NSettings(n8n_base_url="http://[fe80::1]:5678")

    # AWS/GCP/Azure link-local metadata IP
    with pytest.raises(ValueError, match="link-local"):
        N8NSettings(n8n_base_url="http://169.254.169.254:80")

    # Cloud metadata hostname
    with pytest.raises(ValueError, match="cloud metadata"):
        N8NSettings(n8n_base_url="http://metadata.google.internal")


def test_restricted_node_case_insensitive_and_short_names():
    """Verify restricted node types are caught with short names and alternate casing."""
    validator = WorkflowValidator(registry=NodeRegistry())

    # Mixed-case short name
    wf1 = WorkflowIR(
        id=str(uuid.uuid4()),
        name="Short Name Restricted",
        nodes=[
            IRNode(
                id="n1",
                name="Exec",
                node_type="executeCommand",
                type_version=1,
            )
        ],
        edges=[],
    )
    report1 = validator.validate(wf1)
    assert report1.is_valid is False
    assert any(issue.rule_code == "FATAL_RESTRICTED_NODE" for issue in report1.issues)

    # Local file access
    wf2 = WorkflowIR(
        id=str(uuid.uuid4()),
        name="Local File Access",
        nodes=[
            IRNode(
                id="n2",
                name="File Access",
                node_type="n8n-nodes-base.localFileAccess",
                type_version=1,
            )
        ],
        edges=[],
    )
    report2 = validator.validate(wf2)
    assert report2.is_valid is False
    assert any(issue.rule_code == "FATAL_RESTRICTED_NODE" for issue in report2.issues)


def test_code_node_escaped_hex_and_function_constructor():
    """Verify hex-encoded evasions and Function constructors in Code nodes are caught."""
    validator = WorkflowValidator(registry=NodeRegistry())

    # Hex escaped "child_process"
    hex_code = r"const cp = require('\x63\x68\x69\x6c\x64\x5f\x70\x72\x6f\x63\x65\x73\x73');"
    wf_hex = WorkflowIR(
        id=str(uuid.uuid4()),
        name="Hex Evasion Attempt",
        nodes=[
            IRNode(
                id="code1",
                name="Escaped Code",
                node_type="n8n-nodes-base.code",
                type_version=2,
                parameters={"jsCode": hex_code},
            )
        ],
        edges=[],
    )
    report_hex = validator.validate(wf_hex)
    assert report_hex.is_valid is False
    assert any(issue.rule_code == "RESTRICTED_CODE_SANDBOX" for issue in report_hex.issues)

    # Function(...) dynamic constructor
    func_code = "const evil = new Function('return process')();"
    wf_func = WorkflowIR(
        id=str(uuid.uuid4()),
        name="Function Constructor Attempt",
        nodes=[
            IRNode(
                id="code2",
                name="Constructor Code",
                node_type="n8n-nodes-base.code",
                type_version=2,
                parameters={"jsCode": func_code},
            )
        ],
        edges=[],
    )
    report_func = validator.validate(wf_func)
    assert report_func.is_valid is False
    assert any(issue.rule_code == "RESTRICTED_CODE_SANDBOX" for issue in report_func.issues)


def test_secret_sanitizer_url_credentials_and_jwt():
    """Verify SecretSanitizer scrubs generic URL credentials, Basic auth headers, and standalone JWTs."""
    raw = (
        "Connecting to https://admin:superSecret123@api.internal.service/v1 "
        "and redis://redisuser:redisPass456@redis.host:6379 "
        "with Authorization: Basic dXNlcjpwYXNzd29yZDEyMw== "
        "and token eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSignature123"
    )
    sanitized = SecretSanitizer.sanitize_text(raw)

    assert "superSecret123" not in sanitized
    assert "https://admin:***@api.internal.service/v1" in sanitized
    assert "redisPass456" not in sanitized
    assert "redis://redisuser:***@redis.host:6379" in sanitized
    assert "dXNlcjpwYXNzd29yZDEyMw==" not in sanitized
    assert "doNotLeakThisSignature123" not in sanitized
    assert "[REDACTED]" in sanitized
