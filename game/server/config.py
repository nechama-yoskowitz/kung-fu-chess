"""
Server configuration loaded from environment variables.

Provides defaults suitable for local development without Docker.
In Docker, override via environment variables or docker-compose.yml.

Usage:
    from game.server.config import ServerConfig
    cfg = ServerConfig.from_env()
    print(cfg.db_dsn)
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ServerConfig:
    """
    Immutable configuration snapshot read at startup.
    """

    # WebSocket transport
    ws_host: str
    ws_port: int

    # Database backend: "sqlite" or "postgres"
    db_backend: str

    # SQLite (only used when db_backend == "sqlite")
    sqlite_path: str

    # PostgreSQL DSN (only used when db_backend == "postgres")
    # Example: postgresql://kfc:secret@localhost:5432/kungfu_chess
    postgres_dsn: str

    # Redis URL (only used when REDIS_ENABLED=1)
    redis_url: str
    redis_enabled: bool

    # Logging
    log_level: str

    # HTTP API Gateway port (Stage 6)
    # Set KFC_HTTP_PORT to change; 0 means "do not start HTTP server"
    http_port: int

    @classmethod
    def from_env(cls) -> "ServerConfig":
        """Build a config from current environment variables."""
        db_backend = os.environ.get("KFC_DB_BACKEND", "sqlite").lower()
        redis_enabled = os.environ.get("KFC_REDIS_ENABLED", "0").strip() == "1"

        return cls(
            ws_host=os.environ.get("KFC_WS_HOST", "localhost"),
            ws_port=int(os.environ.get("KFC_WS_PORT", "8765")),
            db_backend=db_backend,
            sqlite_path=os.environ.get("KFC_SQLITE_PATH", "kungfu_chess.db"),
            postgres_dsn=os.environ.get(
                "KFC_POSTGRES_DSN",
                "postgresql://kfc:kfc_secret@localhost:5432/kungfu_chess",
            ),
            redis_url=os.environ.get("KFC_REDIS_URL", "redis://localhost:6379/0"),
            redis_enabled=redis_enabled,
            log_level=os.environ.get("KFC_LOG_LEVEL", "INFO"),
            http_port=int(os.environ.get("KFC_HTTP_PORT", "8080")),
        )
