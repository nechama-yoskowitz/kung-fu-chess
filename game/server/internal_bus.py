"""
Internal inter-server message bus for Kung-Fu Chess.

Stage 4: enables cross-server routing of game commands and responses.
Stage 5: adds create_room, join_room, matchmaking session creation,
         reconnect, and broadcast fan-out so that a client on any server
         can fully participate in a game owned by any other server.

Channel names
─────────────
  kfc:server:<server_id>:commands   — inbound commands for that server
  kfc:server:<server_id>:events     — inbound events/responses for that server

Message types (all JSON-serialisable)
──────────────────────────────────────
Sent on :commands channel:
  game_command        — move_request / jump_request forwarding (Stage 4)
  create_room_cmd     — gateway asks owner to create a room (Stage 5)
  join_room_cmd       — gateway asks owner to add a player/viewer (Stage 5)
  create_session_cmd  — gateway asks owner to create a matchmaking session (Stage 5)
  reconnect_cmd       — gateway asks owner to restore a disconnected player (Stage 5)

Sent on :events channel:
  game_response       — owner replies to game_command (Stage 4)
  room_event          — owner replies with room/session result (Stage 5)
  broadcast_event     — owner pushes game broadcasts to all connection servers (Stage 5)
"""

import asyncio
import json
import logging
import threading
import uuid
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

_NS = "kfc"


def commands_channel(server_id: str) -> str:
    """Return the Redis channel for inbound commands to server_id."""
    return f"{_NS}:server:{server_id}:commands"


def events_channel(server_id: str) -> str:
    """Return the Redis channel for inbound events/responses to server_id."""
    return f"{_NS}:server:{server_id}:events"


# ── Typed dict helpers ────────────────────────────────────────────────────────

def make_game_command(
    *,
    source_server: str,
    target_server: str,
    room_id: str,
    username: str,
    cmd: str,
    payload: dict,
    request_id: str | None = None,
) -> dict:
    """Build a GameCommand envelope."""
    return {
        "type": "game_command",
        "request_id": request_id or uuid.uuid4().hex,
        "source_server": source_server,
        "target_server": target_server,
        "room_id": room_id,
        "username": username,
        "cmd": cmd,
        "payload": payload,
    }


def make_game_response(
    *,
    source_server: str,
    target_server: str,
    room_id: str,
    username: str,
    request_id: str,
    response: str | None,
    broadcasts: list[str],
) -> dict:
    """Build a GameResponse envelope."""
    return {
        "type": "game_response",
        "request_id": request_id,
        "source_server": source_server,
        "target_server": target_server,
        "room_id": room_id,
        "username": username,
        "response": response,
        "broadcasts": broadcasts,
    }


# ── Stage 5: new command envelope helpers ────────────────────────────────────

def make_create_room_cmd(
    *,
    source_server: str,
    target_server: str,
    room_id: str,
    username: str,
    rating: int,
    request_id: str | None = None,
) -> dict:
    """Gateway → owner: please create a room with this room_id and add username as first player."""
    return {
        "type": "create_room_cmd",
        "request_id": request_id or uuid.uuid4().hex,
        "source_server": source_server,
        "target_server": target_server,
        "room_id": room_id,
        "username": username,
        "rating": rating,
    }


def make_join_room_cmd(
    *,
    source_server: str,
    target_server: str,
    room_id: str,
    username: str,
    rating: int,
    request_id: str | None = None,
) -> dict:
    """Gateway → owner: add username to an existing room."""
    return {
        "type": "join_room_cmd",
        "request_id": request_id or uuid.uuid4().hex,
        "source_server": source_server,
        "target_server": target_server,
        "room_id": room_id,
        "username": username,
        "rating": rating,
    }


def make_create_session_cmd(
    *,
    source_server: str,
    target_server: str,
    room_id: str,
    player1_username: str,
    player1_rating: int,
    player1_server: str,
    player2_username: str,
    player2_rating: int,
    player2_server: str,
    request_id: str | None = None,
) -> dict:
    """Gateway → owner: create an authoritative matchmaking session for two players."""
    return {
        "type": "create_session_cmd",
        "request_id": request_id or uuid.uuid4().hex,
        "source_server": source_server,
        "target_server": target_server,
        "room_id": room_id,
        "player1_username": player1_username,
        "player1_rating": player1_rating,
        "player1_server": player1_server,
        "player2_username": player2_username,
        "player2_rating": player2_rating,
        "player2_server": player2_server,
    }


def make_reconnect_cmd(
    *,
    source_server: str,
    target_server: str,
    room_id: str,
    session_id: str,
    username: str,
    color: str,
    rating: int,
    request_id: str | None = None,
) -> dict:
    """Gateway → owner: restore a disconnected player."""
    return {
        "type": "reconnect_cmd",
        "request_id": request_id or uuid.uuid4().hex,
        "source_server": source_server,
        "target_server": target_server,
        "room_id": room_id,
        "session_id": session_id,
        "username": username,
        "color": color,
        "rating": rating,
    }


def make_room_event(
    *,
    event_type: str,
    source_server: str,
    target_server: str,
    room_id: str,
    username: str,
    request_id: str,
    payload: dict,
) -> dict:
    """Owner → gateway: response to a room/session/reconnect command."""
    return {
        "type": "room_event",
        "event_type": event_type,   # "room_created", "room_joined", "session_created", "reconnected", "error"
        "request_id": request_id,
        "source_server": source_server,
        "target_server": target_server,
        "room_id": room_id,
        "username": username,
        "payload": payload,
    }


def make_broadcast_event(
    *,
    source_server: str,
    target_server: str,
    room_id: str,
    broadcasts: list[str],
) -> dict:
    """Owner → connection-server: push authoritative game broadcasts."""
    return {
        "type": "broadcast_event",
        "source_server": source_server,
        "target_server": target_server,
        "room_id": room_id,
        "broadcasts": broadcasts,
    }


# ── Handler type aliases ──────────────────────────────────────────────────────

CommandHandler = Callable[[dict], Awaitable[None]]
ResponseHandler = Callable[[dict], Awaitable[None]]


# ─── NullInternalMessageBus ───────────────────────────────────────────────────

class NullInternalMessageBus:
    """
    In-process message bus for tests and single-server mode.

    Publish calls are delivered synchronously to any registered handler
    for that channel.  Because tests are single-process, every "bus
    instance" needs to share a common registry so that publish on one
    router reaches the handler registered by another router.

    Use ``NullInternalMessageBus.shared()`` to obtain the process-wide
    singleton, or create independent instances (they will not cross-talk).
    """

    _shared: "NullInternalMessageBus | None" = None

    @classmethod
    def shared(cls) -> "NullInternalMessageBus":
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    @classmethod
    def reset_shared(cls) -> None:
        """Clear the shared singleton — call between tests."""
        cls._shared = None

    def __init__(self) -> None:
        # channel → list of async handler coroutine-functions
        self._handlers: dict[str, list[CommandHandler]] = {}

    def subscribe(self, channel: str, handler: CommandHandler) -> None:
        """Register an async handler for messages on channel."""
        self._handlers.setdefault(channel, []).append(handler)

    def unsubscribe(self, channel: str, handler: CommandHandler) -> None:
        handlers = self._handlers.get(channel, [])
        if handler in handlers:
            handlers.remove(handler)

    def publish(self, channel: str, message: dict) -> None:
        """
        Deliver message to all handlers subscribed to channel.

        Runs handlers synchronously using asyncio.get_event_loop().run_until_complete
        when not already inside a running loop, or schedules them on the
        running loop when called from within async code.
        """
        handlers = self._handlers.get(channel, [])
        if not handlers:
            logger.debug(f"NullBus: no handler for channel {channel!r}")
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        for handler in handlers:
            if loop is not None and loop.is_running():
                # Schedule as a task on the running loop
                loop.create_task(handler(message))
            else:
                # Called from sync code — run directly
                asyncio.run(handler(message))

    async def publish_async(self, channel: str, message: dict) -> None:
        """Async version of publish — awaits each handler directly."""
        for handler in self._handlers.get(channel, []):
            await handler(message)

    def close(self) -> None:
        """No-op for interface compatibility."""
        pass


# ─── RedisInternalMessageBus ──────────────────────────────────────────────────

class RedisInternalMessageBus:
    """
    Redis Pub/Sub-based message bus for multi-server production mode.

    Requires TWO redis connections:
    - publisher_client: used for PUBLISH (the normal sync client from RedisStore)
    - A new dedicated connection is created internally for SUBSCRIBE, because
      a subscribed Redis connection cannot issue regular commands.

    The subscriber runs in a daemon thread.  Received messages are dispatched
    to async handlers via loop.call_soon_threadsafe so they run on the server's
    asyncio event loop without blocking it.
    """

    def __init__(self, redis_url: str, own_server_id: str, loop: asyncio.AbstractEventLoop | None = None):
        """
        Parameters
        ----------
        redis_url
            Redis connection URL, e.g. "redis://redis:6379/0".
        own_server_id
            This server's stable identity.  Used to construct channel names.
        loop
            The asyncio event loop to schedule handler coroutines on.
            Defaults to the running loop at construction time.
        """
        import redis as redis_mod
        self._own_server_id = own_server_id
        self._loop = loop
        self._redis_url = redis_url

        # Publisher client (normal, non-blocking commands)
        self._pub_client = redis_mod.Redis.from_url(redis_url, decode_responses=True)

        # Subscriber client (dedicated — must not run other commands)
        self._sub_client = redis_mod.Redis.from_url(redis_url, decode_responses=True)
        self._pubsub = self._sub_client.pubsub(ignore_subscribe_messages=True)

        # channel → list of async handlers
        self._handlers: dict[str, list[CommandHandler]] = {}

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def subscribe(self, channel: str, handler: CommandHandler) -> None:
        """Subscribe to a Redis channel and register an async handler."""
        already_subscribed = channel in self._handlers
        self._handlers.setdefault(channel, []).append(handler)
        if not already_subscribed:
            self._pubsub.subscribe(channel)
            logger.debug(f"RedisBus: subscribed to channel {channel!r}")

    def unsubscribe(self, channel: str, handler: CommandHandler) -> None:
        handlers = self._handlers.get(channel, [])
        if handler in handlers:
            handlers.remove(handler)
        if not handlers:
            self._pubsub.unsubscribe(channel)
            self._handlers.pop(channel, None)

    def publish(self, channel: str, message: dict) -> None:
        """Publish a message dict to a Redis Pub/Sub channel (synchronous)."""
        try:
            self._pub_client.publish(channel, json.dumps(message))
        except Exception as exc:
            logger.error(f"RedisBus: publish to {channel!r} failed: {exc}")

    async def publish_async(self, channel: str, message: dict) -> None:
        """Async wrapper around publish — runs in executor to avoid blocking."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.publish, channel, message)

    def start_listener(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """
        Start the background subscriber thread.

        Must be called after the asyncio event loop is running.
        """
        self._loop = loop or self._loop or asyncio.get_event_loop()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._listen_loop,
            name=f"redis-bus-{self._own_server_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"RedisBus: listener thread started for server {self._own_server_id!r}")

    def close(self) -> None:
        """Stop the listener thread and close Redis connections."""
        self._stop_event.set()
        try:
            self._pubsub.unsubscribe()
            self._pubsub.close()
        except Exception:
            pass
        try:
            self._pub_client.close()
        except Exception:
            pass
        try:
            self._sub_client.close()
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info(f"RedisBus: closed for server {self._own_server_id!r}")

    def _listen_loop(self) -> None:
        """Thread body: poll Redis Pub/Sub and dispatch to async handlers."""
        while not self._stop_event.is_set():
            try:
                # listen() blocks until a message arrives or timeout
                for raw_msg in self._pubsub.listen():
                    if self._stop_event.is_set():
                        break
                    if raw_msg is None:
                        continue
                    if raw_msg.get("type") != "message":
                        continue
                    channel = raw_msg.get("channel", "")
                    data = raw_msg.get("data", "")
                    self._dispatch(channel, data)
            except Exception as exc:
                if not self._stop_event.is_set():
                    logger.warning(f"RedisBus: listener error: {exc}; reconnecting…")
                    import time
                    time.sleep(1.0)

    def _dispatch(self, channel: str, raw_data: str) -> None:
        """Parse a raw Pub/Sub message and schedule handler coroutines."""
        try:
            msg = json.loads(raw_data)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(f"RedisBus: invalid JSON on {channel!r}: {exc}")
            return

        handlers = self._handlers.get(channel, [])
        if not handlers:
            logger.debug(f"RedisBus: no handler for channel {channel!r}")
            return

        loop = self._loop
        if loop is None or not loop.is_running():
            logger.warning(f"RedisBus: event loop unavailable for dispatch on {channel!r}")
            return

        for handler in handlers:
            asyncio.run_coroutine_threadsafe(handler(msg), loop)
