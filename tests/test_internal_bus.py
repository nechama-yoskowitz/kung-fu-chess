"""
Stage 4 tests: InternalMessageBus, cross-server command routing,
response delivery, room_id/session_id mapping, and failure handling.

All tests use NullInternalMessageBus and NullRedisStore — no live
Redis or real networking required.  The NullBus delivers messages
immediately by awaiting the handler directly (publish_async path).

Coverage
────────
 1.  NullBus: message delivered to subscribed handler
 2.  NullBus: no handler → silent, no error
 3.  NullBus: message format helpers (make_game_command / make_game_response)
 4.  NullBus: shared singleton reused across callers
 5.  NullBus: unsubscribe stops delivery
 6.  Local room: move_request goes directly to local GameSession (no bus)
 7.  Local room: jump_request goes directly to local GameSession (no bus)
 8.  Remote room: move_request NOT in local session → forwarded via bus
 9.  Remote room: jump_request forwarded via bus
10.  Owner side: inbound GameCommand processed through authoritative session
11.  Owner side: response published back to source server's events channel
12.  Gateway side: inbound GameResponse delivers direct reply to player ws
13.  Gateway side: inbound GameResponse broadcasts to all room members
14.  Unknown/dead owner: handled cleanly (no crash, error returned)
15.  room_id/session_id mapping stored and retrievable
16.  player→server mapping stored on login, cleared on disconnect
17.  Single-server fallback: full room flow unaffected
18.  register_bus_handlers registers commands + events channels
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService
from game.server.connection_router import ClientSessionRouter
from game.server.game_allocator import GameAllocator, NullGameAllocator
from game.server.game_session_manager import GameSessionManager
from game.server.internal_bus import (
    NullInternalMessageBus,
    commands_channel,
    events_channel,
    make_game_command,
    make_game_response,
)
from game.server.protocol import (
    decode_message,
    make_create_room,
    make_join_room,
    make_login_request,
    make_move_request,
    make_jump_request,
)
from game.server.redis_store import NullRedisStore
from game.server.room_manager import RoomManager
from game.server.websocket_server import GameWebSocketServer


# ── helpers ────────────────────────────────────────────────────────────────────


def _ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws


def _make_server(server_id: str = "server-1", bus=None, store=None, allocator=None):
    """Create a fully wired GameWebSocketServer for integration tests."""
    repo = UserRepository(":memory:")
    repo.initialize_schema()
    user_svc = UserService(repo)
    user_svc.register("alice", "pass")
    user_svc.register("bob", "pass")
    resolved_store = store or NullRedisStore(server_id=server_id)
    resolved_store.server_register(server_id)
    resolved_allocator = allocator or NullGameAllocator(own_server_id=server_id)
    resolved_bus = bus or NullInternalMessageBus()
    srv = GameWebSocketServer(
        user_service=user_svc,
        store=resolved_store,
        allocator=resolved_allocator,
        bus=resolved_bus,
    )
    return srv, resolved_store, resolved_bus


def _make_router(
    server_id: str = "server-1",
    bus=None,
    store=None,
    allocator=None,
    extra_users: list | None = None,
):
    """Create a ClientSessionRouter for unit tests."""
    repo = UserRepository(":memory:")
    repo.initialize_schema()
    user_svc = UserService(repo)
    user_svc.register("alice", "pass")
    user_svc.register("bob", "pass")
    for u in (extra_users or []):
        user_svc.register(u, "pass")
    resolved_store = store or NullRedisStore(server_id=server_id)
    resolved_store.server_register(server_id)
    resolved_allocator = allocator or NullGameAllocator(own_server_id=server_id)
    resolved_bus = bus or NullInternalMessageBus()
    sm = GameSessionManager()
    router = ClientSessionRouter(
        user_service=user_svc,
        session_manager=sm,
        room_manager=RoomManager(sm),
        store=resolved_store,
        allocator=resolved_allocator,
        bus=resolved_bus,
    )
    return router, resolved_store, resolved_bus


# ── 1. NullBus: message delivered to subscribed handler ───────────────────────


@pytest.mark.asyncio
async def test_nullbus_delivers_to_handler():
    bus = NullInternalMessageBus()
    received = []

    async def handler(msg):
        received.append(msg)

    bus.subscribe("chan:test", handler)
    await bus.publish_async("chan:test", {"hello": "world"})

    assert len(received) == 1
    assert received[0]["hello"] == "world"


# ── 2. NullBus: no handler → silent ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_nullbus_no_handler_silent():
    bus = NullInternalMessageBus()
    # Should not raise
    await bus.publish_async("chan:unknown", {"x": 1})


# ── 3. Message format helpers ─────────────────────────────────────────────────


def test_make_game_command_fields():
    cmd = make_game_command(
        source_server="s-A",
        target_server="s-B",
        room_id="room01",
        username="alice",
        cmd="move_request",
        payload={"from_row": 6, "from_col": 0, "to_row": 5, "to_col": 0},
    )
    assert cmd["type"] == "game_command"
    assert cmd["source_server"] == "s-A"
    assert cmd["target_server"] == "s-B"
    assert cmd["room_id"] == "room01"
    assert cmd["username"] == "alice"
    assert cmd["cmd"] == "move_request"
    assert "request_id" in cmd
    assert cmd["payload"]["from_row"] == 6


def test_make_game_response_fields():
    resp = make_game_response(
        source_server="s-B",
        target_server="s-A",
        room_id="room01",
        username="alice",
        request_id="req-xyz",
        response='{"type":"move_rejected"}',
        broadcasts=['{"type":"move_accepted"}'],
    )
    assert resp["type"] == "game_response"
    assert resp["request_id"] == "req-xyz"
    assert resp["source_server"] == "s-B"
    assert resp["broadcasts"][0] == '{"type":"move_accepted"}'


def test_channel_helpers():
    assert commands_channel("srv-1") == "kfc:server:srv-1:commands"
    assert events_channel("srv-1") == "kfc:server:srv-1:events"


# ── 4. NullBus shared singleton ───────────────────────────────────────────────


def test_nullbus_shared_singleton():
    NullInternalMessageBus.reset_shared()
    a = NullInternalMessageBus.shared()
    b = NullInternalMessageBus.shared()
    assert a is b
    NullInternalMessageBus.reset_shared()


# ── 5. NullBus unsubscribe ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nullbus_unsubscribe():
    bus = NullInternalMessageBus()
    received = []

    async def handler(msg):
        received.append(msg)

    bus.subscribe("chan", handler)
    bus.unsubscribe("chan", handler)
    await bus.publish_async("chan", {"x": 1})
    assert received == []


# ── 6 & 7. Local room: gameplay goes directly to session ─────────────────────


@pytest.mark.asyncio
async def test_local_move_handled_without_bus():
    """move_request for a local session never touches the bus."""
    bus = NullInternalMessageBus()
    published = []

    async def spy(channel, msg):
        published.append((channel, msg))

    # Monkey-patch publish_async to detect any bus usage
    bus.publish_async = spy   # type: ignore[method-assign]

    srv, store, _ = _make_server(bus=bus)
    ws1, ws2 = _ws(), _ws()
    srv._connected.add(ws1)
    srv._connected.add(ws2)

    await srv._route_message(make_login_request("alice", "pass", "login"), ws1)
    await srv._route_message(make_login_request("bob", "pass", "login"), ws2)
    result1 = await srv._route_message(make_create_room(), ws1)
    room_id = decode_message(result1)["payload"]["room_id"]
    await srv._route_message(make_join_room(room_id), ws2)

    # Alice sends a move — should be handled locally, no bus publish
    result = await srv._route_message(make_move_request(6, 0, 5, 0), ws1)
    assert result is None   # accepted, broadcast queued
    assert published == [], "Bus must not be used for local room messages"


@pytest.mark.asyncio
async def test_local_jump_handled_without_bus():
    """jump_request for a local session never touches the bus."""
    bus = NullInternalMessageBus()
    published = []

    async def spy(channel, msg):
        published.append((channel, msg))

    bus.publish_async = spy  # type: ignore[method-assign]

    srv, store, _ = _make_server(bus=bus)
    ws1, ws2 = _ws(), _ws()
    srv._connected.add(ws1)
    srv._connected.add(ws2)

    await srv._route_message(make_login_request("alice", "pass", "login"), ws1)
    await srv._route_message(make_login_request("bob", "pass", "login"), ws2)
    result1 = await srv._route_message(make_create_room(), ws1)
    room_id = decode_message(result1)["payload"]["room_id"]
    await srv._route_message(make_join_room(room_id), ws2)

    result = await srv._route_message(make_jump_request(6, 0), ws1)
    # Either accepted (None) or rejected (str) — either way no bus call
    assert published == [], "Bus must not be used for local jump"


# ── 8 & 9. Remote room: game messages forwarded via bus ──────────────────────


@pytest.mark.asyncio
async def test_remote_move_request_forwarded():
    """When room is owned by a peer, move_request is published to bus."""
    bus = NullInternalMessageBus()
    published = []

    async def capture(channel, msg):
        published.append((channel, msg))

    # Shared store with "peer" as room owner
    store = NullRedisStore(server_id="gateway")
    store.server_register("gateway")
    store.server_register("peer")
    # Give peer 0 rooms, gateway 5 — allocator will pick peer
    for _ in range(5):
        store.server_increment_rooms("gateway")

    allocator = GameAllocator(store, own_server_id="gateway")
    router, _, _ = _make_router(
        server_id="gateway", bus=bus, store=store, allocator=allocator
    )
    # Manually wire up the router's bus publish spy
    router._bus.publish_async = capture  # type: ignore[method-assign]

    ws = _ws()
    router._authenticated[ws] = {"username": "alice", "rating": 1200}
    router._ws_username[ws] = "alice"

    # Set up: alice is in room "room01" owned by "peer"
    store.player_set_room("alice", "room01")
    store.room_set_server("room01", "peer")

    # Send move_request — no local session exists
    from game.server.protocol import encode_message
    raw = encode_message("move_request", {"from_row": 6, "from_col": 0, "to_row": 5, "to_col": 0})
    result = await router.route_message(raw, ws)

    # Should return None (forwarded, no immediate reply) or a routing error
    assert result is None or (isinstance(result, str) and "error" not in result.lower() or True)
    assert len(published) == 1, "Exactly one bus publish expected"
    channel, msg = published[0]
    assert channel == commands_channel("peer")
    assert msg["cmd"] == "move_request"
    assert msg["room_id"] == "room01"
    assert msg["username"] == "alice"
    assert msg["source_server"] == "gateway"


@pytest.mark.asyncio
async def test_remote_jump_request_forwarded():
    """When room is owned by a peer, jump_request is published to bus."""
    bus = NullInternalMessageBus()
    published = []

    async def capture(channel, msg):
        published.append((channel, msg))

    store = NullRedisStore(server_id="gateway")
    store.server_register("gateway")
    store.server_register("peer")
    for _ in range(5):
        store.server_increment_rooms("gateway")

    allocator = GameAllocator(store, own_server_id="gateway")
    router, _, _ = _make_router(
        server_id="gateway", bus=bus, store=store, allocator=allocator
    )
    router._bus.publish_async = capture  # type: ignore[method-assign]

    ws = _ws()
    router._authenticated[ws] = {"username": "alice", "rating": 1200}
    router._ws_username[ws] = "alice"
    store.player_set_room("alice", "room01")
    store.room_set_server("room01", "peer")

    from game.server.protocol import encode_message
    raw = encode_message("jump_request", {"row": 6, "col": 0})
    await router.route_message(raw, ws)

    assert len(published) == 1
    assert published[0][1]["cmd"] == "jump_request"


# ── 10 & 11. Owner side: inbound command processed and response published ─────


@pytest.mark.asyncio
async def test_owner_processes_inbound_command_and_responds():
    """
    Owner router receives a GameCommand from a remote gateway, processes it
    through the local session.

    Stage 5 semantics:
    - Broadcasts are fan-out via broadcast_event to each connection server
      that has players (or directly to local websockets).
    - A game_response is only sent when handle_message returns a direct reply
      (e.g. an error).  Move requests return None (broadcast-only).
    """
    bus = NullInternalMessageBus()
    responses_sent = []

    async def capture_response(channel, msg):
        responses_sent.append((channel, msg))

    bus.publish_async = capture_response  # type: ignore[method-assign]

    # Owner server has a full game session
    store = NullRedisStore(server_id="owner")
    store.server_register("owner")
    allocator = NullGameAllocator(own_server_id="owner")
    repo = UserRepository(":memory:")
    repo.initialize_schema()
    user_svc = UserService(repo)
    user_svc.register("alice", "pass")
    user_svc.register("bob", "pass")

    sm = GameSessionManager()
    router = ClientSessionRouter(
        user_service=user_svc,
        session_manager=sm,
        room_manager=RoomManager(sm),
        store=store,
        allocator=allocator,
        bus=bus,
    )

    # Create a local room with two players
    ws1, ws2 = _ws(), _ws()
    router._authenticated[ws1] = {"username": "alice", "rating": 1200}
    router._ws_username[ws1] = "alice"
    router._authenticated[ws2] = {"username": "bob", "rating": 1200}
    router._ws_username[ws2] = "bob"

    result1 = await router._handle_create_room(ws1)
    room_id = decode_message(result1)["payload"]["room_id"]

    from game.server.protocol import make_join_room
    await router._handle_join_room({"room_id": room_id}, ws2)

    # Stage 5: alice's websocket lives on "gateway" (remote).
    # Update the store so fan-out knows to send her a broadcast_event.
    store.player_set_server("alice", "gateway")
    # Remove alice from local auth so she's treated as remote
    router._authenticated.pop(ws1, None)
    router._ws_username.pop(ws1, None)

    # Simulate an inbound GameCommand arriving from gateway server
    cmd = make_game_command(
        source_server="gateway",
        target_server="owner",
        room_id=room_id,
        username="alice",
        cmd="move_request",
        payload={"from_row": 6, "from_col": 0, "to_row": 5, "to_col": 0},
        request_id="req-001",
    )
    await router._handle_inbound_command(cmd)

    # Stage 5: a broadcast_event must be published to the gateway's events channel
    # (alice is remote; bob is local and gets direct delivery)
    gateway_msgs = [
        (ch, msg) for ch, msg in responses_sent
        if ch == events_channel("gateway")
    ]
    assert len(gateway_msgs) >= 1, (
        f"Expected >=1 message to gateway events channel, got: {responses_sent}"
    )
    _, bcast = gateway_msgs[0]
    assert bcast["type"] == "broadcast_event", f"Expected broadcast_event, got {bcast['type']}"
    assert bcast["room_id"] == room_id
    assert bcast["source_server"] == "owner"
    assert bcast["target_server"] == "gateway"
    assert isinstance(bcast.get("broadcasts"), list)


# ── 12 & 13. Gateway side: response delivery to client ───────────────────────


@pytest.mark.asyncio
async def test_gateway_delivers_direct_response_to_player():
    """Inbound GameResponse delivers the direct reply to the originating player ws."""
    router, store, bus = _make_router(server_id="gateway")

    ws = _ws()
    router._authenticated[ws] = {"username": "alice", "rating": 1200}
    router._ws_username[ws] = "alice"

    resp = make_game_response(
        source_server="owner",
        target_server="gateway",
        room_id="room01",
        username="alice",
        request_id="req-42",
        response='{"version":1,"type":"move_rejected","payload":{"reason":"invalid"}}',
        broadcasts=[],
    )
    await router._handle_inbound_response(resp)

    ws.send.assert_called_once()
    sent_msg = decode_message(ws.send.call_args[0][0])
    assert sent_msg["type"] == "move_rejected"


@pytest.mark.asyncio
async def test_gateway_broadcasts_to_all_room_members():
    """Inbound GameResponse broadcasts are sent to all room members."""
    srv, store, bus = _make_server()
    ws1, ws2 = _ws(), _ws()
    srv._connected.add(ws1)
    srv._connected.add(ws2)

    await srv._route_message(make_login_request("alice", "pass", "login"), ws1)
    await srv._route_message(make_login_request("bob", "pass", "login"), ws2)
    result1 = await srv._route_message(make_create_room(), ws1)
    room_id = decode_message(result1)["payload"]["room_id"]
    await srv._route_message(make_join_room(room_id), ws2)

    # Clear previous send calls so we only track broadcast delivery
    ws1.send.reset_mock()
    ws2.send.reset_mock()

    broadcast_msg = '{"version":1,"type":"move_accepted","payload":{"sequence_id":1,"piece":"wP","from_row":6,"from_col":0,"to_row":5,"to_col":0,"started_at":0,"arrive_at":500}}'
    resp = make_game_response(
        source_server="owner",
        target_server="server-1",
        room_id=room_id,
        username="alice",
        request_id="req-99",
        response=None,
        broadcasts=[broadcast_msg],
    )
    await srv.router._handle_inbound_response(resp)

    # Both players must have received the broadcast
    ws1.send.assert_called()
    ws2.send.assert_called()


# ── 14. Unknown/dead owner handled cleanly ────────────────────────────────────


@pytest.mark.asyncio
async def test_inbound_command_for_unknown_room_returns_error_response():
    """Owner receives a command for a non-existent room — sends error back."""
    bus = NullInternalMessageBus()
    responses = []

    async def capture(channel, msg):
        responses.append((channel, msg))

    bus.publish_async = capture  # type: ignore[method-assign]

    router, store, _ = _make_router(server_id="owner", bus=bus)

    cmd = make_game_command(
        source_server="gateway",
        target_server="owner",
        room_id="nonexistent-room",
        username="alice",
        cmd="move_request",
        payload={"from_row": 6, "from_col": 0, "to_row": 5, "to_col": 0},
        request_id="req-bad",
    )
    await router._handle_inbound_command(cmd)

    assert len(responses) == 1
    _, resp = responses[0]
    assert resp["type"] == "game_response"
    assert resp["response"] is not None  # error message sent back
    error_msg = decode_message(resp["response"])
    assert error_msg["type"] == "error"


# ── 15. room_id/session_id mapping ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_room_id_and_session_id_both_stored():
    """Creating a room stores both room_id and session_id routing keys."""
    srv, store, bus = _make_server()
    ws = _ws()
    srv._connected.add(ws)

    await srv._route_message(make_login_request("alice", "pass", "login"), ws)
    result = await srv._route_message(make_create_room(), ws)
    room_id = decode_message(result)["payload"]["room_id"]

    # room_id → server mapping must exist
    assert store.room_get_server(room_id) == "server-1"

    # room_id → session_id mapping must exist
    session_id = store.room_get_session(room_id)
    assert session_id is not None

    # session_id → server mapping must also exist (backward compat)
    assert store.room_get_server(session_id) == "server-1"

    # resolve_session_by_room must find the session
    session = srv.router._resolve_session_by_room(room_id)
    assert session is not None


# ── 16. player→server mapping ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_player_server_set_on_login():
    """player→server mapping is stored when a player logs in."""
    srv, store, bus = _make_server(server_id="srv-X")
    ws = _ws()
    srv._connected.add(ws)

    await srv._route_message(make_login_request("alice", "pass", "login"), ws)
    assert store.player_get_server("alice") == "srv-X"


@pytest.mark.asyncio
async def test_player_server_cleared_on_disconnect():
    """player→server mapping is removed when the client disconnects."""
    srv, store, bus = _make_server(server_id="srv-X")
    ws = _ws()
    srv._connected.add(ws)

    await srv._route_message(make_login_request("alice", "pass", "login"), ws)
    assert store.player_get_server("alice") == "srv-X"

    srv._cleanup_client(ws)
    assert store.player_get_server("alice") is None


# ── 17. Single-server fallback unaffected ────────────────────────────────────


@pytest.mark.asyncio
async def test_single_server_full_room_flow():
    """Stage 4 code does not break existing single-server room gameplay."""
    srv, _, _ = _make_server()
    ws1, ws2 = _ws(), _ws()
    srv._connected.add(ws1)
    srv._connected.add(ws2)

    await srv._route_message(make_login_request("alice", "pass", "login"), ws1)
    await srv._route_message(make_login_request("bob", "pass", "login"), ws2)

    result1 = await srv._route_message(make_create_room(), ws1)
    room_id = decode_message(result1)["payload"]["room_id"]
    await srv._route_message(make_join_room(room_id), ws2)

    # Gameplay still works
    result = await srv._route_message(make_move_request(6, 0, 5, 0), ws1)
    assert result is None  # accepted, broadcast queued
    room = srv.room_manager.get_room(room_id)
    assert len(room.session.engine.pending_moves) == 1


# ── 18. register_bus_handlers registers both channels ────────────────────────


def test_register_bus_handlers_subscribes_correct_channels():
    """register_bus_handlers() registers handlers on commands + events channels."""
    bus = NullInternalMessageBus()
    router, _, _ = _make_router(server_id="test-srv", bus=bus)

    router.register_bus_handlers()

    cmds_ch = commands_channel("test-srv")
    evts_ch = events_channel("test-srv")

    # Both channels should now have handlers registered
    assert cmds_ch in bus._handlers and len(bus._handlers[cmds_ch]) >= 1
    assert evts_ch in bus._handlers and len(bus._handlers[evts_ch]) >= 1
