"""Typed exceptions for Tavily research and documentation retrieval."""


class TavilyClientError(Exception):
    """Base exception for all Tavily research errors."""

    def __init__(self, message: str, status_code: int = 500, details: str = ""):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


class TavilyAuthError(TavilyClientError):
    """Raised when Tavily authentication fails (invalid or missing API key)."""

    def __init__(self, message: str = "Tavily API key is invalid or unauthorized."):
        super().__init__(message=message, status_code=401)


class TavilyRateLimitError(TavilyClientError):
    """Raised when Tavily rate limits are exceeded (HTTP 429)."""

    def __init__(self, message: str = "Tavily API rate limit exceeded.", retry_after: float = 5.0):
        super().__init__(message=message, status_code=429)
        self.retry_after = retry_after


class TavilyTimeoutError(TavilyClientError):
    """Raised when a Tavily research request exceeds configured timeout."""

    def __init__(self, message: str = "Tavily API request timed out."):
        super().__init__(message=message, status_code=504)


class TavilyAPIError(TavilyClientError):
    """Raised when Tavily responds with a 4xx or 5xx error."""

    pass


class TavilyUnavailableError(TavilyClientError):
    """Raised when Tavily service cannot be reached (DNS, connection drop, offline)."""

    def __init__(self, message: str = "Tavily service is unavailable or unreachable."):
        super().__init__(message=message, status_code=503)
