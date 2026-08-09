"""
Entry point: python -m game.server

Starts the WebSocket server with persistence and optional Redis support.

Repository selection is controlled by the environment variable KFC_DB_BACKEND:
    sqlite   (default) — uses a local SQLite file (good for local dev)
    postgres           — uses a PostgreSQL server (required in Docker/production)

See game/server/config.py for the full list of environment variables.
"""

import asyncio
import logging
import time

from game.logging_config import setup_logging
from game.server.auth.user_service import UserService
from game.server.config import ServerConfig
from game.server.rating.rating_service import RatingService
from game.server.websocket_server import run_server

setup_logging(enable_file=True, log_file="server.log")
logger = logging.getLogger(__name__)


def _build_repository(cfg: ServerConfig):
    """
    Create and initialise the appropriate user repository from config.

    SQLite:   instant, no retry needed.
    Postgres: retries until the DB server is ready (Docker startup delay).
    """
    if cfg.db_backend == "postgres":
        from game.server.auth.postgres_user_repository import PostgresUserRepository
        repo = PostgresUserRepository(cfg.postgres_dsn)
        _wait_for_postgres(repo, max_retries=10, delay=2.0)
    else:
        from game.server.auth.user_repository import UserRepository
        repo = UserRepository(cfg.sqlite_path)
        repo.initialize_schema()

    return repo


def _wait_for_postgres(repo, max_retries: int = 10, delay: float = 2.0) -> None:
    """
    Try to connect and initialise the PostgreSQL schema, retrying on failure.

    PostgreSQL typically needs a few seconds after the container starts
    before it accepts connections — this loop absorbs that startup lag.
    """
    for attempt in range(1, max_retries + 1):
        try:
            repo.initialize_schema()
            logger.info("PostgreSQL ready and schema initialised")
            return
        except Exception as exc:
            if attempt < max_retries:
                logger.warning(
                    f"PostgreSQL not ready (attempt {attempt}/{max_retries}): {exc} "
                    f"— retrying in {delay}s"
                )
                time.sleep(delay)
            else:
                raise RuntimeError(
                    f"PostgreSQL unreachable after {max_retries} attempts"
                ) from exc


def _connect_redis(cfg: ServerConfig):
    """
    Connect to Redis and verify reachability if Redis is enabled.

    Stage 1: only a connectivity check — no state is stored in Redis yet.
    Returns the client on success, None if Redis is disabled.
    """
    if not cfg.redis_enabled:
        logger.info("Redis disabled (KFC_REDIS_ENABLED=0) — skipping")
        return None

    from game.server.redis_client import get_redis_client, ping_redis
    client = get_redis_client(cfg.redis_url)
    ping_redis(client)          # raises ConnectionError if unreachable
    return client


def main() -> None:
    cfg = ServerConfig.from_env()
    # Re-apply logging with the configured level (may differ from module-level default).
    setup_logging(level=cfg.log_level, enable_file=True, log_file="server.log")

    logger.info(
        "Kung-Fu Chess server starting — "
        f"db={cfg.db_backend} "
        f"redis={cfg.redis_enabled} "
        f"ws={cfg.ws_host}:{cfg.ws_port}"
    )

    # ── Persistence ───────────────────────────────────────────────────────────
    repo = _build_repository(cfg)
    user_service = UserService(repo)
    rating_service = RatingService(repository=repo)

    # ── Redis (Stage 1: connection check only) ────────────────────────────────
    _connect_redis(cfg)

    # ── WebSocket server ──────────────────────────────────────────────────────
    print(f"Kung-Fu Chess server listening on ws://{cfg.ws_host}:{cfg.ws_port}")
    try:
        asyncio.run(run_server(
            host=cfg.ws_host,
            port=cfg.ws_port,
            user_service=user_service,
            rating_service=rating_service,
        ))
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
