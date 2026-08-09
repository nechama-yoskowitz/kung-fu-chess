"""
Redis connection factory for Kung-Fu Chess server.

Stage 1: provides a simple sync client used only for health checks
and a ping at startup. No game state is moved to Redis yet.

Stage 2+ will use this to store shared routing/matchmaking state.

Usage:
    from game.server.redis_client import get_redis_client, ping_redis

    client = get_redis_client(redis_url)
    ping_redis(client)   # raises if Redis is unreachable
    client.close()
"""

import logging

logger = logging.getLogger(__name__)


def get_redis_client(redis_url: str):
    """
    Create and return a synchronous Redis client.

    The client is not yet connected — the first command triggers the
    connection. Call ping_redis() to verify connectivity at startup.

    Parameters
    ----------
    redis_url : str
        Redis URL, e.g. "redis://localhost:6379/0"

    Returns
    -------
    redis.Redis
        A synchronous Redis client instance.
    """
    import redis  # type: ignore[import-not-found]
    return redis.Redis.from_url(redis_url, decode_responses=True)


def ping_redis(client, max_retries: int = 5, delay_seconds: float = 1.0) -> None:
    """
    Ping Redis, retrying up to max_retries times.

    Raises ConnectionError if Redis is not reachable after all retries.
    Logs a warning on each failed attempt to aid Docker startup debugging.
    """
    import time
    import redis as redis_mod  # type: ignore[import-not-found]

    for attempt in range(1, max_retries + 1):
        try:
            client.ping()
            logger.info("Redis connection established")
            return
        except (redis_mod.ConnectionError, redis_mod.TimeoutError) as exc:
            if attempt < max_retries:
                logger.warning(
                    f"Redis not ready (attempt {attempt}/{max_retries}): {exc} "
                    f"— retrying in {delay_seconds}s"
                )
                time.sleep(delay_seconds)
            else:
                raise ConnectionError(
                    f"Redis unreachable after {max_retries} attempts: {exc}"
                ) from exc
