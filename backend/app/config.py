"""Global application and service configuration settings."""
import ipaddress
from typing import Optional
from urllib.parse import urlparse
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class N8NSettings(BaseSettings):
    """Configuration for local n8n instance connection."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    N8N_BASE_URL: str = Field(
        default="http://localhost:5678",
        description="Base URL for local n8n instance.",
    )
    N8N_API_KEY: Optional[str] = Field(
        default=None,
        description="n8n REST API key configured in n8n Settings.",
    )
    N8N_TIMEOUT_SEC: float = Field(
        default=10.0,
        description="Timeout in seconds for n8n API requests.",
    )

    @field_validator("N8N_BASE_URL", mode="after")
    @classmethod
    def validate_n8n_base_url(cls, v: str) -> str:
        clean = v.strip().rstrip("/")
        if not clean:
            raise ValueError("N8N_BASE_URL cannot be empty.")
        parsed = urlparse(clean)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid scheme '{parsed.scheme}'. Only http and https are allowed.")
        if not parsed.netloc:
            raise ValueError("Invalid URL: missing host/netloc.")

        # Defensive SSRF: Block cloud metadata and link-local targets
        host = (parsed.hostname or "").lower()
        cloud_metadata_hosts = {
            "169.254.169.254",
            "metadata.google.internal",
            "instance-data",
            "metadata.nic.internal",
        }
        if host in cloud_metadata_hosts or host.startswith("169.254."):
            raise ValueError(f"Target host '{host}' is prohibited by SSRF safety policy (cloud metadata/link-local).")

        # Check IP representations (including IPv6 link-local and IPv4-mapped)
        ip = None
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            pass

        if ip is not None and ip.is_link_local:
            raise ValueError(f"Target IP '{host}' is prohibited by SSRF safety policy (link-local).")

        return clean


class AppSettings(BaseSettings):
    """Global backend application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BACKEND_HOST: str = Field(default="127.0.0.1")
    BACKEND_PORT: int = Field(default=8000)
    ENVIRONMENT: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")

    # Security & API limits
    STUDIO_API_KEY: Optional[str] = Field(default=None, description="Optional pre-shared API key for securing API endpoints")
    MAX_PAYLOAD_BYTES: int = Field(default=2 * 1024 * 1024, description="Max request payload size in bytes (default 2MB)")
    RATE_LIMIT_PER_MINUTE: int = Field(default=120, description="Max requests per minute per IP")
    AUTH_ENFORCED: bool = Field(default=False, description="Enforce mandatory API key authentication even on localhost")



class DatabaseSettings(BaseSettings):
    """PostgreSQL database configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: Optional[str] = Field(
        default=None,
        description="Async PostgreSQL connection string (postgresql+asyncpg://user:pass@host:port/dbname)",
    )
    DB_POOL_SIZE: int = Field(default=5, description="Connection pool size")
    DB_MAX_OVERFLOW: int = Field(default=10, description="Max overflow connections")
    DB_POOL_TIMEOUT: float = Field(default=30.0, description="Pool timeout seconds")

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def validate_and_normalize_database_url(cls, v: Optional[str]) -> Optional[str]:
        if not v or not v.strip():
            return None
        clean = v.strip()
        parsed = urlparse(clean)
        # Check scheme
        if not parsed.scheme.startswith("postgresql"):
            raise ValueError(
                f"Invalid database scheme '{parsed.scheme}'. PostgreSQL is mandatory (postgresql+asyncpg://)."
            )
        # Ensure asyncpg driver is specified
        if parsed.scheme == "postgresql":
            clean = "postgresql+asyncpg://" + clean[len("postgresql://"):]
        return clean

    def get_masked_database_url(self) -> str:
        """Returns connection string with password redacted for safe logging."""
        if not self.DATABASE_URL:
            return "DATABASE_URL_NOT_CONFIGURED"
        parsed = urlparse(self.DATABASE_URL)
        if not parsed.password:
            return self.DATABASE_URL
        # Replace password with ***
        netloc = f"{parsed.username}:***@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"
        return f"{parsed.scheme}://{netloc}{parsed.path}"


class ResearchSettings(BaseSettings):
    """Configuration for Tavily Web Research integration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    TAVILY_API_KEY: Optional[str] = Field(
        default=None,
        description="Tavily API key for web research and documentation extraction.",
    )
    TAVILY_BASE_URL: str = Field(
        default="https://api.tavily.com",
        description="Base URL for Tavily Search and Extract API.",
    )
    TAVILY_SEARCH_DEPTH: str = Field(
        default="basic",
        description="Search depth: 'basic' or 'advanced'.",
    )
    TAVILY_MAX_RESULTS: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum search results per query.",
    )
    TAVILY_TIMEOUT_SEC: float = Field(
        default=15.0,
        gt=0.0,
        description="HTTP request timeout in seconds for Tavily calls.",
    )
    TAVILY_MAX_RETRIES: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Maximum retry attempts on 429 or 5xx responses.",
    )
    TAVILY_CACHE_TTL_HOURS: int = Field(
        default=24,
        ge=1,
        description="Cache TTL in hours for persistent research queries.",
    )
    TAVILY_MAX_RESEARCH_PER_TURN: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum Tavily searches allowed within a single generation turn.",
    )
    TAVILY_MAX_EXTRACT_PER_TURN: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum Tavily page extractions allowed within a single generation turn.",
    )
    TAVILY_MAX_CONTENT_CHARS: int = Field(
        default=6000,
        ge=500,
        description="Maximum text character length retained per source to avoid token bloat.",
    )

    @property
    def is_configured(self) -> bool:
        """Returns True if a non-empty API key is configured."""
        return bool(self.TAVILY_API_KEY and self.TAVILY_API_KEY.strip())


def get_settings() -> AppSettings:
    """Returns global AppSettings instance."""
    return AppSettings()


def get_research_settings() -> ResearchSettings:
    """Returns global ResearchSettings instance."""
    return ResearchSettings()


