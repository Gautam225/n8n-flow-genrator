"""Security middleware components for payload size limiting, rate limiting, and security headers."""
import asyncio
import time
from typing import Any, Callable, Dict, List, Optional
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class PayloadSizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects incoming HTTP requests exceeding the maximum permitted body size."""

    def __init__(self, app: Any, max_bytes: int = 2 * 1024 * 1024):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        limit_str = (
            f"{self.max_bytes // (1024 * 1024)}MB"
            if self.max_bytes >= 1024 * 1024
            else f"{self.max_bytes} bytes"
        )
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Request payload exceeds maximum allowed size ({limit_str})."},
                    )
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})

        # For chunked or streaming requests without Content-Length, wrap receive callable
        bytes_received = 0
        original_receive = request._receive

        async def limited_receive():
            nonlocal bytes_received
            message = await original_receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                bytes_received += len(body)
                if bytes_received > self.max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Request payload stream exceeds maximum allowed size ({limit_str}).",
                    )
            return message

        request._receive = limited_receive
        try:
            return await call_next(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        except Exception as exc:
            # Handle ExceptionGroup wrapping in AnyIO / Python 3.11+ task groups
            sub_exceptions = getattr(exc, "exceptions", None)
            if sub_exceptions:
                for sub in sub_exceptions:
                    if isinstance(sub, HTTPException):
                        return JSONResponse(status_code=sub.status_code, content={"detail": sub.detail})
            raise exc


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """In-memory sliding window rate limiter per client IP address with bounded memory and concurrency safety."""

    MAX_TRACKED_IPS: int = 10000

    def __init__(
        self,
        app: Any,
        requests_per_minute: int = 120,
        rate_limit_per_minute: Optional[int] = None,
    ):
        super().__init__(app)
        self.requests_per_minute = rate_limit_per_minute if rate_limit_per_minute is not None else requests_per_minute
        self.window_seconds = 60.0
        # Map IP -> list of timestamp floats
        self._history: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip health check endpoints from rate limiting
        if request.url.path in ("/healthz", "/docs", "/openapi.json"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        window_start = now - self.window_seconds

        async with self._lock:
            # Prune older timestamps for this client
            timestamps = self._history.get(client_ip, [])
            recent_timestamps = [ts for ts in timestamps if ts > window_start]

            # Periodic cleanup of expired IPs if table grows large
            if len(self._history) > self.MAX_TRACKED_IPS:
                expired_ips = [ip for ip, tss in self._history.items() if not any(t > window_start for t in tss)]
                for ip in expired_ips:
                    del self._history[ip]
                # If still over limit, drop oldest entries
                if len(self._history) > self.MAX_TRACKED_IPS:
                    sorted_ips = sorted(
                        self._history.keys(),
                        key=lambda ip: max(self._history[ip]) if self._history[ip] else 0,
                    )
                    for ip in sorted_ips[: len(self._history) - self.MAX_TRACKED_IPS]:
                        del self._history[ip]

            if len(recent_timestamps) >= self.requests_per_minute:
                self._history[client_ip] = recent_timestamps
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Please wait before submitting more requests."},
                    headers={"Retry-After": "60"},
                )

            recent_timestamps.append(now)
            self._history[client_ip] = recent_timestamps

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces standard defensive HTTP security headers on all responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response
