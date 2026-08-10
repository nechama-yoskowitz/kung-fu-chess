"""
Entry point: python -m game.server

Starts the WebSocket server with persistence and optional Redis support.

Stage 2: Redis is now used as a shared store for matchmaking queue entries,
reconnect metadata, and room/player routing pointers.

Repository selection is controlled by KFC_DB_BACKEND:
    sqlite   (default) — SQLite file (local dev)
    postgres           — PostgreSQL server (Docker / production)

See game/server/config.py for all environment variables.
"""

import asyncio
import logging
import os
import socket
import time

from game.logging_config import setup_logging
from game.server.auth.user_service import UserService
from game.server.config import ServerConfig
from game.server.rating.rating_service import RatingService
from game.server.websocket_server import run_server

setup_logging(enable_file=True, log_file="server.log")
logger = logging.getLogger(__name__)


def _server_id() -> str:
    """
    Stable identity for this server instance.
    Uses KFC_SERVER_ID env var, then Docker hostname, then 'server-1'.
    """
    return os.environ.get("KFC_SERVER_ID", socket.gethostname() or "server-1")


def _build_repository(cfg: ServerConfig):
    """Create and initialise the appropriate user repository from config."""
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
    """Retry PostgreSQL schema init until the server is ready."""
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


def _build_redis_store(cfg: ServerConfig):
    """
    Create a RedisStore if Redis is enabled, otherwise return NullRedisStore.

    Stage 2: the store is used for matchmaking queue metadata,
    reconnect slots, and room/player routing pointers.
    """
    sid = _server_id()

    if not cfg.redis_enabled:
        logger.info("Redis disabled (KFC_REDIS_ENABLED=0) — using in-memory NullRedisStore")
        from game.server.redis_store import NullRedisStore
        return NullRedisStore(server_id=sid)

    from game.server.redis_client import get_redis_client, ping_redis
    from game.server.redis_store import RedisStore
    client = get_redis_client(cfg.redis_url)
    ping_redis(client)
    store = RedisStore(client, server_id=sid)
    logger.info(f"Redis connected — using RedisStore (server_id={sid})")
    return store


def main() -> None:
    cfg = ServerConfig.from_env()
    setup_logging(level=cfg.log_level, enable_file=True, log_file="server.log")

    logger.info(
        "Kung-Fu Chess server starting — "
        f"db={cfg.db_backend} redis={cfg.redis_enabled} "
        f"ws={cfg.ws_host}:{cfg.ws_port} server_id={_server_id()}"
    )

    # ── Persistence ───────────────────────────────────────────────────────────
    repo = _build_repository(cfg)
    user_service = UserService(repo)
    rating_service = RatingService(repository=repo)

    # ── Shared Redis store (Stage 2) ──────────────────────────────────────────
    store = _build_redis_store(cfg)

    # ── WebSocket server ──────────────────────────────────────────────────────
    print(f"Kung-Fu Chess server listening on ws://{cfg.ws_host}:{cfg.ws_port}")
    try:
        asyncio.run(run_server(
            host=cfg.ws_host,
            port=cfg.ws_port,
            user_service=user_service,
            rating_service=rating_service,
            store=store,
        ))
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
