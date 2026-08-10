"""
Game Server allocation for Kung-Fu Chess.

Stage 3: introduces explicit Game Server ownership so that every room is
assigned to exactly one authoritative Game Server instance.

Architecture boundary
─────────────────────
GameAllocator   — chooses which server should own a new room.
RedisStore      — stores shared routing/capacity metadata.
Game Server     — owns Room / GameSession / GameEngine locally.
GameEngine      — single authoritative source of truth (never moves to Redis).

Allocation strategy
───────────────────
Pick the registered Game Server with the lowest current active-room count
(least-loaded first).  If no servers are registered in the shared store,
fall back to the current server's own ID so single-server deployments and
tests continue to work without Redis.

``NullGameAllocator``
─────────────────────
An in-process allocator that always returns a fixed server_id (defaults to
"server-1").  Used in all unit tests to avoid touching Redis.
"""

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ─── Protocol (interface) ─────────────────────────────────────────────────────

@runtime_checkable
class Allocator(Protocol):
    """
    Minimal interface required by ClientSessionRouter.

    Any object that implements ``allocate_server()`` satisfies this protocol.
    """

    def allocate_server(self) -> str:
        """
        Return the server_id that should own the next new room.

        Never raises — falls back to a sensible default when the shared
        registry is unavailable or empty.
        """
        ...


# ─── Production allocator ─────────────────────────────────────────────────────

class GameAllocator:
    """
    Least-loaded Game Server allocator backed by the shared RedisStore.

    Reads the live server registry and picks the server with the fewest
    active rooms.  Falls back to ``fallback_server_id`` when the registry
    is empty or unavailable.

    Parameters
    ----------
    store
        A ``RedisStore`` or ``NullRedisStore`` instance that implements the
        Stage 3 server-registry methods.
    own_server_id : str
        The stable identity of the current server process.  Used as the
        fallback when no peers are registered.
    """

    def __init__(self, store, own_server_id: str):
        self._store = store
        self._own_server_id = own_server_id

    @property
    def own_server_id(self) -> str:
        return self._own_server_id

    def allocate_server(self) -> str:
        """
        Return the server_id of the least-loaded active Game Server.

        Algorithm
        ─────────
        1. Fetch the live server list from the shared store (sorted by
           active_rooms ascending, dead servers already filtered out).
        2. Return the first entry's server_id (lowest room count).
        3. If the list is empty (no registered servers), return own_server_id
           so that single-server and test environments still work correctly.
        """
        try:
            active = self._store.server_list_active()
        except Exception as exc:
            logger.warning(
                f"GameAllocator: could not read server list ({exc}); "
                f"falling back to own server {self._own_server_id!r}"
            )
            return self._own_server_id

        if not active:
            logger.debug(
                f"GameAllocator: no active servers in registry; "
                f"using own server {self._own_server_id!r}"
            )
            return self._own_server_id

        chosen = active[0]
        logger.debug(
            f"GameAllocator: allocated {chosen.server_id!r} "
            f"(active_rooms={chosen.active_rooms}, "
            f"candidates={len(active)})"
        )
        return chosen.server_id

    def is_local(self, server_id: str) -> bool:
        """Return True if server_id refers to this server instance."""
        return server_id == self._own_server_id


# ─── Null allocator (tests / no-Redis mode) ───────────────────────────────────

class NullGameAllocator:
    """
    In-process allocator for tests and no-Redis deployments.

    Always returns ``own_server_id``, so the current server is always
    considered the owner.  This means:
    - No Redis interaction.
    - All GameSessions are always created locally.
    - All existing tests pass without modification.

    Parameters
    ----------
    own_server_id : str
        Identity of the current server (default ``"server-1"``).
    """

    def __init__(self, own_server_id: str = "server-1"):
        self._own_server_id = own_server_id

    @property
    def own_server_id(self) -> str:
        return self._own_server_id

    def allocate_server(self) -> str:
        """Always return own server ID."""
        return self._own_server_id

    def is_local(self, server_id: str) -> bool:
        """Always True — NullGameAllocator owns every room locally."""
        return True
