"""
Redis-backed shared state store for Kung-Fu Chess.

Stage 2: moves shared temporary metadata that prevents horizontal scaling
out of per-process dicts and into Redis.

Stage 3 additions:
  kfc:gameserver:<server_id>   — Hash of game server registration/capacity
  kfc:gameservers:active       — Sorted set: server_id → active_rooms score

Logical namespaces (full list):
  kfc:matchmaking:<username>   — players waiting for a match
  kfc:reconnect:<username>     — disconnected player slots
  kfc:room:<room_id>:server    — which server owns a room
  kfc:player:<username>:room   — which room a player is in
  kfc:gameserver:<server_id>   — game server registration metadata (Stage 3)
  kfc:gameservers:active       — active server set ordered by room count (Stage 3)

Live game state (GameSession / GameEngine) stays in-process.
This module never stores board state, active moves, clocks, or collisions.

All methods are synchronous (using the redis-py sync client) because
GameSession event-bus callbacks are synchronous and the server runs
in a single asyncio event loop per process.

A ``NullRedisStore`` provides identical behaviour backed by plain dicts
for tests that run without a live Redis instance.
"""

import json
import logging
import time
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)

# Key TTLs
_MATCHMAKING_ENTRY_TTL = 120      # seconds — auto-expire stale queue entries
_RECONNECT_TTL = 30               # slightly longer than RECONNECT_TIMEOUT
_ROOM_SERVER_TTL = 3600           # 1 hour — rooms seldom live longer
_PLAYER_ROOM_TTL = 3600
_GAMESERVER_TTL = 30              # seconds — server must heartbeat within this window

# Heartbeat interval used by the server process (exported for use in server loop)
HEARTBEAT_INTERVAL = 10           # seconds

# Key prefix
_NS = "kfc"


def _key(*parts: str) -> str:
    return ":".join([_NS, *parts])


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class MatchQueueEntry:
    """Metadata for a player in the shared matchmaking queue."""
    username: str
    rating: int
    server_id: str        # which server instance this player is connected to
    enqueue_time: float   # time.monotonic()-compatible value for ordering


@dataclass
class ReconnectEntry:
    """Metadata for a player who disconnected and may reconnect."""
    username: str
    color: str
    room_id: str | None
    session_id: str
    disconnect_time: float
    deadline: float


@dataclass
class GameServerInfo:
    """Metadata for a registered game server instance."""
    server_id: str
    active_rooms: int
    registered_at: float   # time.monotonic()-compatible
    last_seen: float        # updated on every heartbeat


# ─── Redis store ──────────────────────────────────────────────────────────────

class RedisStore:
    """
    Shared coordination state backed by Redis.

    Responsibilities:
    - matchmaking queue metadata (kfc:matchmaking:*)
    - reconnect slot metadata (kfc:reconnect:*)
    - room→server routing (kfc:room:<id>:server)
    - player→room routing (kfc:player:<name>:room)
    """

    def __init__(self, redis_client, server_id: str = "server-1"):
        self._r = redis_client
        self._server_id = server_id

    # ── Matchmaking ────────────────────────────────────────────────────────

    def matchmaking_enqueue(self, username: str, rating: int) -> bool:
        """
        Add a player to the shared matchmaking queue.

        Returns True if added, False if already present.
        """
        key = _key("matchmaking", username)
        if self._r.exists(key):
            return False
        entry = MatchQueueEntry(
            username=username,
            rating=rating,
            server_id=self._server_id,
            enqueue_time=time.monotonic(),
        )
        self._r.setex(key, _MATCHMAKING_ENTRY_TTL, json.dumps(asdict(entry)))
        # Add to a sorted set ordered by enqueue_time for FIFO matching
        self._r.zadd(_key("matchmaking", "queue"), {username: entry.enqueue_time})
        return True

    def matchmaking_remove(self, username: str) -> MatchQueueEntry | None:
        """Remove a player from the queue. Returns the entry if found."""
        key = _key("matchmaking", username)
        raw = self._r.get(key)
        if raw is None:
            return None
        self._r.delete(key)
        self._r.zrem(_key("matchmaking", "queue"), username)
        data = json.loads(raw)
        return MatchQueueEntry(**data)

    def matchmaking_is_queued(self, username: str) -> bool:
        """Return True if the player is in the queue."""
        return bool(self._r.exists(_key("matchmaking", username)))

    def matchmaking_get_all(self) -> list[MatchQueueEntry]:
        """
        Return all queue entries sorted by enqueue_time (oldest first).
        """
        sorted_set_key = _key("matchmaking", "queue")
        # ZRANGEBYSCORE with full range, scores = enqueue times
        usernames = self._r.zrange(sorted_set_key, 0, -1)
        entries = []
        for username in usernames:
            key = _key("matchmaking", username)
            raw = self._r.get(key)
            if raw is None:
                # Stale entry in sorted set — clean up
                self._r.zrem(sorted_set_key, username)
                continue
            data = json.loads(raw)
            entries.append(MatchQueueEntry(**data))
        return entries

    def matchmaking_get_queue_size(self) -> int:
        """Return the number of players in the queue."""
        return self._r.zcard(_key("matchmaking", "queue"))

    def matchmaking_get_timed_out(self, timeout_seconds: float) -> list[MatchQueueEntry]:
        """
        Remove and return all queue entries older than timeout_seconds.
        """
        cutoff = time.monotonic() - timeout_seconds
        sorted_set_key = _key("matchmaking", "queue")
        # All entries with score <= cutoff are timed out
        old_usernames = self._r.zrangebyscore(sorted_set_key, "-inf", cutoff)
        timed_out = []
        for username in old_usernames:
            entry = self.matchmaking_remove(username)
            if entry:
                timed_out.append(entry)
        return timed_out

    # ── Reconnect ──────────────────────────────────────────────────────────

    def reconnect_start(
        self,
        username: str,
        color: str,
        room_id: str | None,
        session_id: str,
        timeout_seconds: float,
    ) -> ReconnectEntry:
        """Register a disconnected player. TTL matches the reconnect window."""
        now = time.monotonic()
        entry = ReconnectEntry(
            username=username,
            color=color,
            room_id=room_id,
            session_id=session_id,
            disconnect_time=now,
            deadline=now + timeout_seconds,
        )
        key = _key("reconnect", username)
        ttl = int(timeout_seconds) + 5   # a few extra seconds of margin
        self._r.setex(key, ttl, json.dumps(asdict(entry)))
        logger.debug(f"Reconnect slot created: {username} (TTL={ttl}s)")
        return entry

    def reconnect_get(self, username: str) -> ReconnectEntry | None:
        """
        Return the reconnect entry if it exists and has not expired.

        Returns None if not found (TTL expired or never registered).
        """
        key = _key("reconnect", username)
        raw = self._r.get(key)
        if raw is None:
            return None
        data = json.loads(raw)
        entry = ReconnectEntry(**data)
        # Double-check deadline against wall clock
        if time.monotonic() > entry.deadline:
            self._r.delete(key)
            return None
        return entry

    def reconnect_cancel(self, username: str) -> ReconnectEntry | None:
        """Remove and return a reconnect entry (e.g. after successful restore)."""
        key = _key("reconnect", username)
        raw = self._r.get(key)
        if raw is None:
            return None
        self._r.delete(key)
        return ReconnectEntry(**json.loads(raw))

    def reconnect_has_pending(self, username: str) -> bool:
        """Return True if a valid reconnect slot exists for this user."""
        return self.reconnect_get(username) is not None

    def reconnect_count(self) -> int:
        """Return the number of active reconnect slots (approximate)."""
        return len(self._r.keys(_key("reconnect", "*")))

    def reconnect_get_all(self) -> list[ReconnectEntry]:
        """Return all currently-stored reconnect entries."""
        keys = self._r.keys(_key("reconnect", "*"))
        entries = []
        for key in keys:
            raw = self._r.get(key)
            if raw:
                try:
                    entries.append(ReconnectEntry(**json.loads(raw)))
                except Exception:
                    pass
        return entries

    # ── Room / player routing ──────────────────────────────────────────────

    def room_set_server(self, room_id: str, server_id: str) -> None:
        """Record which server owns a room."""
        self._r.setex(_key("room", room_id, "server"), _ROOM_SERVER_TTL, server_id)

    def room_get_server(self, room_id: str) -> str | None:
        """Return the server_id owning the room, or None."""
        val = self._r.get(_key("room", room_id, "server"))
        return val  # already a string (decode_responses=True)

    def room_delete(self, room_id: str) -> None:
        """Remove routing metadata for a room."""
        self._r.delete(_key("room", room_id, "server"))

    def player_set_room(self, username: str, room_id: str) -> None:
        """Record which room a player is currently in."""
        self._r.setex(_key("player", username, "room"), _PLAYER_ROOM_TTL, room_id)

    def player_get_room(self, username: str) -> str | None:
        """Return the room_id the player is currently in, or None."""
        return self._r.get(_key("player", username, "room"))

    def player_clear_room(self, username: str) -> None:
        """Remove the player→room mapping."""
        self._r.delete(_key("player", username, "room"))

    # ── Game Server Registry (Stage 3) ────────────────────────────────────

    def server_register(self, server_id: str) -> GameServerInfo:
        """
        Register this server instance in the shared registry.

        Writes a hash at kfc:gameserver:<server_id> with an initial
        active_rooms of 0 and adds it to the active sorted set.
        Called once at server startup.
        """
        now = time.monotonic()
        info = GameServerInfo(
            server_id=server_id,
            active_rooms=0,
            registered_at=now,
            last_seen=now,
        )
        key = _key("gameserver", server_id)
        self._r.hset(key, mapping=asdict(info))
        self._r.expire(key, _GAMESERVER_TTL)
        # Sorted set score = active_rooms (0 at startup)
        self._r.zadd(_key("gameservers", "active"), {server_id: 0})
        logger.info(f"Game server registered: server_id={server_id}")
        return info

    def server_heartbeat(self, server_id: str) -> None:
        """
        Refresh the TTL and last_seen timestamp for this server.

        Must be called at least every _GAMESERVER_TTL seconds to prevent
        the server from being considered dead.
        """
        key = _key("gameserver", server_id)
        now = time.monotonic()
        # Only update last_seen if the key still exists
        if self._r.exists(key):
            self._r.hset(key, "last_seen", now)
            self._r.expire(key, _GAMESERVER_TTL)
        else:
            # Key expired between heartbeats — re-register with current count
            active = int(self._r.zscore(_key("gameservers", "active"), server_id) or 0)
            registered_at = now
            info = GameServerInfo(
                server_id=server_id,
                active_rooms=active,
                registered_at=registered_at,
                last_seen=now,
            )
            self._r.hset(key, mapping=asdict(info))
            self._r.expire(key, _GAMESERVER_TTL)
            logger.warning(f"Re-registered server after missed heartbeat: {server_id}")

    def server_deregister(self, server_id: str) -> None:
        """Remove this server from the registry (called at clean shutdown)."""
        self._r.delete(_key("gameserver", server_id))
        self._r.zrem(_key("gameservers", "active"), server_id)
        logger.info(f"Game server deregistered: server_id={server_id}")

    def server_list_active(self) -> list[GameServerInfo]:
        """
        Return all game servers that currently have a live hash key
        (i.e. have sent a heartbeat within _GAMESERVER_TTL seconds),
        sorted by active_rooms ascending (least loaded first).
        """
        # Sorted set gives us server_ids ordered by score (active_rooms)
        members = self._r.zrange(_key("gameservers", "active"), 0, -1, withscores=True)
        result = []
        stale = []
        for server_id, score in members:
            key = _key("gameserver", server_id)
            raw = self._r.hgetall(key)
            if not raw:
                # Hash expired — server is dead; clean up sorted set entry
                stale.append(server_id)
                continue
            try:
                info = GameServerInfo(
                    server_id=raw["server_id"],
                    active_rooms=int(raw.get("active_rooms", 0)),
                    registered_at=float(raw.get("registered_at", 0)),
                    last_seen=float(raw.get("last_seen", 0)),
                )
                result.append(info)
            except (KeyError, ValueError):
                stale.append(server_id)
        if stale:
            for s in stale:
                self._r.zrem(_key("gameservers", "active"), s)
        # Sort by active_rooms (score may be slightly stale; hash value is authoritative)
        result.sort(key=lambda x: x.active_rooms)
        return result

    def server_increment_rooms(self, server_id: str) -> int:
        """
        Atomically increment the active room count for a server.
        Returns the new count.
        """
        key = _key("gameserver", server_id)
        new_count = self._r.hincrby(key, "active_rooms", 1)
        # Keep sorted set score in sync
        self._r.zadd(_key("gameservers", "active"), {server_id: new_count})
        return int(new_count)

    def server_decrement_rooms(self, server_id: str) -> int:
        """
        Atomically decrement the active room count for a server (floor 0).
        Returns the new count.
        """
        key = _key("gameserver", server_id)
        new_count = self._r.hincrby(key, "active_rooms", -1)
        if new_count < 0:
            new_count = 0
            self._r.hset(key, "active_rooms", 0)
        self._r.zadd(_key("gameservers", "active"), {server_id: new_count})
        return int(new_count)

    def server_get_info(self, server_id: str) -> GameServerInfo | None:
        """Return current metadata for a specific server, or None if not found."""
        key = _key("gameserver", server_id)
        raw = self._r.hgetall(key)
        if not raw:
            return None
        try:
            return GameServerInfo(
                server_id=raw["server_id"],
                active_rooms=int(raw.get("active_rooms", 0)),
                registered_at=float(raw.get("registered_at", 0)),
                last_seen=float(raw.get("last_seen", 0)),
            )
        except (KeyError, ValueError):
            return None

    # ── Health ─────────────────────────────────────────────────────────────

    def ping(self) -> bool:
        """Return True if Redis is reachable."""
        try:
            return self._r.ping()
        except Exception:
            return False


# ─── Null (no-op) store for tests / no-Redis mode ────────────────────────────

class NullRedisStore:
    """
    In-memory drop-in for RedisStore.

    Used when Redis is disabled (tests, local dev without Docker).
    Provides identical public API backed by plain Python dicts.
    Not thread-safe — fine for single-process use.
    """

    def __init__(self, server_id: str = "server-1"):
        self._server_id = server_id
        self._mm: dict[str, MatchQueueEntry] = {}       # username → entry
        self._mm_order: list[str] = []                   # insertion order
        self._rc: dict[str, ReconnectEntry] = {}         # username → entry
        self._room_server: dict[str, str] = {}           # room_id → server_id
        self._player_room: dict[str, str] = {}           # username → room_id
        self._servers: dict[str, GameServerInfo] = {}    # server_id → info (Stage 3)

    # ── Matchmaking ────────────────────────────────────────────────────────

    def matchmaking_enqueue(self, username: str, rating: int) -> bool:
        if username in self._mm:
            return False
        entry = MatchQueueEntry(
            username=username,
            rating=rating,
            server_id=self._server_id,
            enqueue_time=time.monotonic(),
        )
        self._mm[username] = entry
        self._mm_order.append(username)
        return True

    def matchmaking_remove(self, username: str) -> MatchQueueEntry | None:
        entry = self._mm.pop(username, None)
        if entry and username in self._mm_order:
            self._mm_order.remove(username)
        return entry

    def matchmaking_is_queued(self, username: str) -> bool:
        return username in self._mm

    def matchmaking_get_all(self) -> list[MatchQueueEntry]:
        return [self._mm[u] for u in self._mm_order if u in self._mm]

    def matchmaking_get_queue_size(self) -> int:
        return len(self._mm)

    def matchmaking_get_timed_out(self, timeout_seconds: float) -> list[MatchQueueEntry]:
        cutoff = time.monotonic() - timeout_seconds
        timed_out = []
        for username in list(self._mm_order):
            entry = self._mm.get(username)
            if entry and entry.enqueue_time <= cutoff:
                self.matchmaking_remove(username)
                timed_out.append(entry)
        return timed_out

    # ── Reconnect ──────────────────────────────────────────────────────────

    def reconnect_start(self, username, color, room_id, session_id, timeout_seconds) -> ReconnectEntry:
        now = time.monotonic()
        entry = ReconnectEntry(
            username=username, color=color, room_id=room_id,
            session_id=session_id, disconnect_time=now,
            deadline=now + timeout_seconds,
        )
        self._rc[username] = entry
        return entry

    def reconnect_get(self, username: str) -> ReconnectEntry | None:
        entry = self._rc.get(username)
        if entry is None:
            return None
        if time.monotonic() > entry.deadline:
            del self._rc[username]
            return None
        return entry

    def reconnect_cancel(self, username: str) -> ReconnectEntry | None:
        return self._rc.pop(username, None)

    def reconnect_has_pending(self, username: str) -> bool:
        return self.reconnect_get(username) is not None

    def reconnect_count(self) -> int:
        return len(self._rc)

    def reconnect_get_all(self) -> list[ReconnectEntry]:
        return list(self._rc.values())

    # ── Room / player routing ──────────────────────────────────────────────

    def room_set_server(self, room_id: str, server_id: str) -> None:
        self._room_server[room_id] = server_id

    def room_get_server(self, room_id: str) -> str | None:
        return self._room_server.get(room_id)

    def room_delete(self, room_id: str) -> None:
        self._room_server.pop(room_id, None)

    def player_set_room(self, username: str, room_id: str) -> None:
        self._player_room[username] = room_id

    def player_get_room(self, username: str) -> str | None:
        return self._player_room.get(username)

    def player_clear_room(self, username: str) -> None:
        self._player_room.pop(username, None)

    # ── Game Server Registry (Stage 3) ────────────────────────────────────

    def server_register(self, server_id: str) -> GameServerInfo:
        now = time.monotonic()
        info = GameServerInfo(
            server_id=server_id,
            active_rooms=0,
            registered_at=now,
            last_seen=now,
        )
        self._servers[server_id] = info
        return info

    def server_heartbeat(self, server_id: str) -> None:
        info = self._servers.get(server_id)
        if info:
            self._servers[server_id] = GameServerInfo(
                server_id=info.server_id,
                active_rooms=info.active_rooms,
                registered_at=info.registered_at,
                last_seen=time.monotonic(),
            )

    def server_deregister(self, server_id: str) -> None:
        self._servers.pop(server_id, None)

    def server_list_active(self) -> list[GameServerInfo]:
        return sorted(self._servers.values(), key=lambda x: x.active_rooms)

    def server_increment_rooms(self, server_id: str) -> int:
        info = self._servers.get(server_id)
        if info is None:
            return 0
        new_count = info.active_rooms + 1
        self._servers[server_id] = GameServerInfo(
            server_id=info.server_id,
            active_rooms=new_count,
            registered_at=info.registered_at,
            last_seen=info.last_seen,
        )
        return new_count

    def server_decrement_rooms(self, server_id: str) -> int:
        info = self._servers.get(server_id)
        if info is None:
            return 0
        new_count = max(0, info.active_rooms - 1)
        self._servers[server_id] = GameServerInfo(
            server_id=info.server_id,
            active_rooms=new_count,
            registered_at=info.registered_at,
            last_seen=info.last_seen,
        )
        return new_count

    def server_get_info(self, server_id: str) -> GameServerInfo | None:
        return self._servers.get(server_id)

    def ping(self) -> bool:
        return True
