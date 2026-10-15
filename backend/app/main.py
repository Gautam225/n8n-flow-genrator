"""FastAPI application entrypoint for n8n Workflow AI Studio."""
import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler

from backend.app.config import get_settings
from backend.app.api.v1.integrations import router as integrations_router
from backend.app.api.v1.conversations import router as conversations_router
from backend.app.security.middleware import (
    PayloadSizeLimitMiddleware,
    RateLimiterMiddleware,
    SecurityHeadersMiddleware,
)
from backend.app.security.sanitizer import sanitize_secrets

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title="n8n Workflow AI Studio API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)

# 1. Payload size limiting (mitigate DoS / memory exhaustion)
app.add_middleware(PayloadSizeLimitMiddleware, max_bytes=settings.MAX_PAYLOAD_BYTES)

# 2. Sliding window IP rate limiter (mitigate brute force / abuse)
app.add_middleware(RateLimiterMiddleware, rate_limit_per_minute=settings.RATE_LIMIT_PER_MINUTE)

# 3. Security headers (defense in depth against clickjacking, sniffing, etc.)
app.add_middleware(SecurityHeadersMiddleware)

# 4. CORS configuration for local frontend studio (outermost to process OPTIONS preflights)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Global exception handler catching unexpected errors.

    Logs sanitized error information to prevent secret exposure in logs,
    and returns a safe generic 500 response without internal stack traces.
    """
    if isinstance(exc, StarletteHTTPException):
        return await http_exception_handler(request, exc)
    if isinstance(exc, RequestValidationError):
        return await request_validation_exception_handler(request, exc)

    sanitized_err = sanitize_secrets(str(exc))
    logger.error("Unhandled server exception on %s %s: %s", request.method, request.url.path, sanitized_err)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."},
    )


app.include_router(integrations_router, prefix="/api/v1")
app.include_router(conversations_router, prefix="/api/v1")


@app.get("/healthz")
async def healthz():
    """Service health check."""
    return {"status": "ok"}
