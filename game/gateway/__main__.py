"""
Entry point: python -m game.gateway

Starts the HTTP API Gateway.

Environment variables (same set as game.server, plus):
    KFC_HTTP_HOST      — bind host   (default: 0.0.0.0)
    KFC_HTTP_PORT      — bind port   (default: 8080)
    KFC_DB_BACKEND     — sqlite | postgres
    KFC_POSTGRES_DSN   — postgres DSN (when db_backend == postgres)
    KFC_SQLITE_PATH    — SQLite path  (when db_backend == sqlite)
    KFC_LOG_LEVEL      — INFO | DEBUG | WARNING ...
"""

import asyncio
import logging
import os
import time

from aiohttp import web

from game.gateway.app import create_app
from game.logging_config import setup_logging
from game.server.config import ServerConfig


logger = logging.getLogger(__name__)


def _build_repository(cfg: ServerConfig):
    """Mirror the same repository bootstrap used by game.server.__main__."""
    if cfg.db_backend == "postgres":
        from game.server.auth.postgres_user_repository import PostgresUserRepository
        repo = PostgresUserRepository(cfg.postgres_dsn)
        _wait_for_postgres(repo)
    else:
        from game.server.auth.user_repository import UserRepository
        repo = UserRepository(cfg.sqlite_path)
        repo.initialize_schema()
    return repo


def _wait_for_postgres(repo, max_retries: int = 10, delay: float = 2.0) -> None:
    """Retry until PostgreSQL is ready (same logic as game.server.__main__)."""
    for attempt in range(1, max_retries + 1):
        try:
            repo.initialize_schema()
            logger.info("PostgreSQL ready and schema initialised")
            return
        except Exception as exc:
            if attempt < max_retries:
                logger.warning(
                    f"PostgreSQL not ready (attempt {attempt}/{max_retries}): {exc}"
                    f" — retrying in {delay}s"
                )
                time.sleep(delay)
            else:
                raise RuntimeError(
                    f"PostgreSQL unreachable after {max_retries} attempts"
                ) from exc


def main() -> None:
    cfg = ServerConfig.from_env()
    setup_logging(level=cfg.log_level, enable_file=False)

    http_host = os.environ.get("KFC_HTTP_HOST", "0.0.0.0")
    http_port = cfg.http_port

    logger.info(
        f"API Gateway starting — db={cfg.db_backend} "
        f"http={http_host}:{http_port}"
    )

    repo = _build_repository(cfg)
    try:
        from game.server.auth.user_service import UserService
        user_service = UserService(repo)

        app = create_app(user_service)
        web.run_app(app, host=http_host, port=http_port, access_log=logger)
    finally:
        repo.close()


if __name__ == "__main__":
    main()
