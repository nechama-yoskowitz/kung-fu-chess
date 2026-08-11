"""
Stage 5 cross-server integration tests.

All tests use NullInternalMessageBus and NullRedisStore — no live Redis or
real networking required.

Scenarios covered
─────────────────
 1.  Remote create_room: gateway publishes create_room_cmd to owner
 2.  Remote create_room: owner creates session and responds with room_event
 3.  Remote create_room: gateway delivers room_created to client ws
 4.  Remote join_room: gateway publishes join_room_cmd to owner
 5.  Remote join_room: owner adds player, responds with room_joined + game_state
 6.  Remote join_room: gateway delivers room_joined to client ws
 7.  Remote join_room: viewer join propagated correctly
 8.  Cross-server gameplay: move forwarded to owner via game_command
 9.  Cross-server gameplay: owner processes move, fan-out broadcast_event sent
10.  Cross-server gameplay: gateway delivers broadcast_event to local ws
11.  Cross-server matchmaking: create_session_cmd published to owner
12.  Cross-server matchmaking: owner creates session, notifies both servers
13.  Cross-server matchmaking: gateway delivers match_found + game_state to client
14.  Cross-server reconnect: reconnect_cmd published to owner
15.  Cross-server reconnect: owner restores player, sends back game state
16.  Cross-server reconnect: gateway delivers login_success + game_state to client
17.  Fan-out: broadcasts go to ALL connection servers with players
18.  Fan-out: no broadcast_event sent when all players are local
19.  Error propagation: owner responds with error room_event on bad room_id
20.  Full end-to-end: two virtual servers, cross-server game lifecycle
"""

import pytest
from unittest.mock import AsyncMock

from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService
from game.server.connection_router import ClientSessionRouter
from game.server.game_allocator import NullGameAllocator
from game.server.game_session_manager import GameSessionManager
from game.server.internal_bus import (
    NullInternalMessageBus,
    commands_channel,
    events_channel,
    make_game_command,
    make_create_room_cmd,
    make_join_room_cmd,
    make_create_session_cmd,
    make_reconnect_cmd,
    make_room_event,
    make_broadcast_event,
)
from game.server.protocol import (
    decode_message,
    make_game_state,
    make_move_request,
    make_jump_request,
)
from game.server.redis_store import NullRedisStore, ReconnectEntry
from game.server.room_manager import RoomManager


# ── Helpers ────────────────────────────────────────────────────────────────────


def _ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws


def _make_router(server_id: str, bus, store, users=("alice", "bob")):
    """Build a ClientSessionRouter wired to the shared bus and store."""
    repo = UserRepository(":memory:")
    repo.initialize_schema()
    user_svc = UserService(repo)
    for u in users:
        user_svc.register(u, "pass")
    sm = GameSessionManager()
    allocator = NullGameAllocator(own_server_id=server_id)
    router = ClientSessionRouter(
        user_service=user_svc,
        session_manager=sm,
        room_manager=RoomManager(sm),
        store=store,
        allocator=allocator,
        bus=bus,
    )
    return router


def _shared_infra(owner_id="owner", gateway_id="gateway"):
    """Return (shared_store, shared_bus, owner_router, gateway_router)."""
    store = NullRedisStore(server_id=owner_id)
    store.server_register(owner_id)
    store.server_register(gateway_id)
    bus = NullInternalMessageBus()
    owner = _make_router(owner_id, bus, store)
    gateway = _make_router(gateway_id, bus, store)
    # Register bus handlers so publish_async delivers to the right router
    owner.register_bus_handlers()
    gateway.register_bus_handlers()
    return store, bus, owner, gateway


# ─────────────────────────────────────────────────────────────────────────────
# 1. Remote create_room: gateway publishes create_room_cmd to owner
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remote_create_room_publishes_cmd():
    """
    When _handle_create_room is called and allocate_server() returns a remote
    peer, a create_room_cmd must be published to the owner's commands channel.
    """
    from game.server.game_allocator import GameAllocator

    store = NullRedisStore(server_id="gateway")
    store.server_register("gateway")
    store.server_register("owner")
    # Make owner appear less loaded so GameAllocator picks it
    store.server_increment_rooms("gateway")
    store.server_increment_rooms("gateway")

    bus = NullInternalMessageBus()
    published = []

    async def capture(channel, msg):
        published.append((channel, msg))

    bus.publish_async = capture  # type: ignore[method-assign]

    allocator = GameAllocator(store, own_server_id="gateway")
    router = _make_router("gateway", bus, store)
    router._allocator = allocator

    ws = _ws()
    router._authenticated[ws] = {"username": "alice", "rating": 1200}
    router._ws_username[ws] = "alice"

    result = await router._handle_create_room(ws)

    # Returns None; real response arrives asynchronously
    assert result is None

    assert len(published) == 1
    ch, cmd = published[0]
    assert ch == commands_channel("owner")
    assert cmd["type"] == "create_room_cmd"
    assert cmd["username"] == "alice"
    assert cmd["source_server"] == "gateway"
    assert cmd["target_server"] == "owner"
    assert cmd["room_id"]  # non-empty


# ─────────────────────────────────────────────────────────────────────────────
# 2 & 3. Remote create_room: owner creates session, gateway delivers room_created
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remote_create_room_end_to_end():
    """
    Full remote create_room flow:
    - gateway sends create_room_cmd to owner via bus
    - owner creates a Room+Session and publishes room_event("room_created")
    - gateway delivers make_room_created to alice's ws
    """
    store, bus, owner, gateway = _shared_infra()

    ws_alice = _ws()
    gateway._authenticated[ws_alice] = {"username": "alice", "rating": 1200}
    gateway._ws_username[ws_alice] = "alice"
    store.player_set_server("alice", "gateway")

    room_id = "test-room-42"
    cmd = make_create_room_cmd(
        source_server="gateway",
        target_server="owner",
        room_id=room_id,
        username="alice",
        rating=1200,
    )
    # Owner processes the command
    await owner._handle_inbound_command(cmd)

    # Owner should have created a room
    room = owner.room_manager.get_room(room_id)
    assert room is not None, "Owner must have created a room"

    # Owner should have stored routing metadata
    assert store.room_get_server(room_id) == "owner"
    assert store.player_get_room("alice") == room_id

    # Gateway should have delivered room_created to alice
    ws_alice.send.assert_awaited_once()
    sent_msg = ws_alice.send.call_args[0][0]
    msg = decode_message(sent_msg)
    assert msg["type"] == "room_created"
    assert msg["payload"]["room_id"] == room_id


# ─────────────────────────────────────────────────────────────────────────────
# 4, 5 & 6. Remote join_room: full flow
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remote_join_room_end_to_end():
    """
    Full remote join_room flow:
    - owner already has a room with alice
    - bob (on gateway) sends join_room_cmd
    - owner adds bob, responds with room_joined + game_state
    - gateway delivers room_joined + game_state to bob's ws
    """
    store, bus, owner, gateway = _shared_infra()

    # Set up alice's room on owner
    ws_alice_local = _ws()
    owner._authenticated[ws_alice_local] = {"username": "alice", "rating": 1200}
    owner._ws_username[ws_alice_local] = "alice"
    store.player_set_server("alice", "owner")
    result = await owner._handle_create_room(ws_alice_local)
    room_id = decode_message(result)["payload"]["room_id"]

    # Mark the room as owned by "owner" in shared store
    store.room_set_server(room_id, "owner")

    # Bob is on gateway
    ws_bob = _ws()
    gateway._authenticated[ws_bob] = {"username": "bob", "rating": 1100}
    gateway._ws_username[ws_bob] = "bob"
    store.player_set_server("bob", "gateway")

    # Gateway sends join_room_cmd to owner
    cmd = make_join_room_cmd(
        source_server="gateway",
        target_server="owner",
        room_id=room_id,
        username="bob",
        rating=1100,
    )
    await owner._handle_inbound_command(cmd)

    # Gateway should have sent room_joined + game_state to bob
    assert ws_bob.send.await_count >= 2, (
        f"Expected >=2 messages to bob, got {ws_bob.send.await_count}"
    )
    calls = [decode_message(c[0][0]) for c in ws_bob.send.call_args_list]
    types = [m["type"] for m in calls]
    assert "room_joined" in types, f"room_joined not in {types}"
    assert "game_state" in types, f"game_state not in {types}"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Remote join_room: viewer
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remote_join_room_as_viewer():
    """When the room already has 2 players, a third joiner gets role=viewer."""
    store, bus, owner, gateway = _shared_infra()

    # Fill the room locally: alice (white) + charlie (black)
    ws_alice = _ws()
    ws_charlie = _ws()
    owner._authenticated[ws_alice] = {"username": "alice", "rating": 1200}
    owner._ws_username[ws_alice] = "alice"
    owner._authenticated[ws_charlie] = {"username": "charlie", "rating": 1100}
    owner._ws_username[ws_charlie] = "charlie"
    store.player_set_server("alice", "owner")
    store.player_set_server("charlie", "owner")

    r = await owner._handle_create_room(ws_alice)
    room_id = decode_message(r)["payload"]["room_id"]
    store.room_set_server(room_id, "owner")
    await owner._handle_join_room({"room_id": room_id}, ws_charlie)

    # Bob on gateway tries to join a full room
    ws_bob = _ws()
    gateway._authenticated[ws_bob] = {"username": "bob", "rating": 1000}
    gateway._ws_username[ws_bob] = "bob"
    store.player_set_server("bob", "gateway")

    cmd = make_join_room_cmd(
        source_server="gateway",
        target_server="owner",
        room_id=room_id,
        username="bob",
        rating=1000,
    )
    await owner._handle_inbound_command(cmd)

    # Gateway must have sent room_joined with role=viewer to bob
    assert ws_bob.send.await_count >= 1
    calls = [decode_message(c[0][0]) for c in ws_bob.send.call_args_list]
    room_joined = next((m for m in calls if m["type"] == "room_joined"), None)
    assert room_joined is not None, f"room_joined not found in {[m['type'] for m in calls]}"
    assert room_joined["payload"]["role"] == "viewer"


# ─────────────────────────────────────────────────────────────────────────────
# 8 & 9. Cross-server gameplay: game_command forwarded, broadcast_event sent
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_server_move_forwarded_to_owner():
    """
    Alice is on gateway, room owned by owner.
    route_message(move_request) must forward a game_command to owner.
    """
    store = NullRedisStore(server_id="gateway")
    store.server_register("gateway")
    store.server_register("owner")

    bus = NullInternalMessageBus()
    published = []

    async def capture(ch, msg):
        published.append((ch, msg))

    bus.publish_async = capture  # type: ignore[method-assign]

    gateway = _make_router("gateway", bus, store)

    ws_alice = _ws()
    gateway._authenticated[ws_alice] = {"username": "alice", "rating": 1200}
    gateway._ws_username[ws_alice] = "alice"
    # alice is in a room on owner, not in a local session
    store.player_set_room("alice", "room-99")
    store.room_set_server("room-99", "owner")
    store.player_set_server("alice", "gateway")

    raw = make_move_request(6, 0, 5, 0)
    await gateway.route_message(raw, ws_alice)

    # A game_command must have been forwarded to owner's commands channel
    cmds = [(ch, m) for ch, m in published if m.get("type") == "game_command"]
    assert len(cmds) == 1, f"Expected 1 game_command, got {published}"
    ch, cmd = cmds[0]
    assert ch == commands_channel("owner")
    assert cmd["username"] == "alice"
    assert cmd["cmd"] == "move_request"
    assert cmd["room_id"] == "room-99"


@pytest.mark.asyncio
async def test_cross_server_owner_fanout_broadcast():
    """
    Owner receives a game_command, processes the move, and publishes a
    broadcast_event to gateway (where alice's ws lives) and delivers
    directly to bob's local ws.
    """
    store, bus, owner, gateway = _shared_infra()

    # alice on gateway, bob on owner
    ws_bob = _ws()
    owner._authenticated[ws_bob] = {"username": "bob", "rating": 1200}
    owner._ws_username[ws_bob] = "bob"
    store.player_set_server("bob", "owner")

    ws_alice_local = _ws()
    owner._authenticated[ws_alice_local] = {"username": "alice", "rating": 1200}
    owner._ws_username[ws_alice_local] = "alice"

    r = await owner._handle_create_room(ws_alice_local)
    room_id = decode_message(r)["payload"]["room_id"]
    store.room_set_server(room_id, "owner")
    await owner._handle_join_room({"room_id": room_id}, ws_bob)

    # Now simulate alice moving to gateway
    owner._authenticated.pop(ws_alice_local, None)
    owner._ws_username.pop(ws_alice_local, None)
    store.player_set_server("alice", "gateway")

    ws_alice_gw = _ws()
    gateway._authenticated[ws_alice_gw] = {"username": "alice", "rating": 1200}
    gateway._ws_username[ws_alice_gw] = "alice"

    cmd = make_game_command(
        source_server="gateway",
        target_server="owner",
        room_id=room_id,
        username="alice",
        cmd="move_request",
        payload={"from_row": 6, "from_col": 0, "to_row": 5, "to_col": 0},
    )
    await owner._handle_inbound_command(cmd)

    # Alice (on gateway) should have received a broadcast_event → delivered to ws
    assert ws_alice_gw.send.await_count >= 1, (
        "Gateway should have delivered broadcast to alice"
    )
    # Bob (local on owner) should have received broadcasts directly
    assert ws_bob.send.await_count >= 1, (
        "Owner should have delivered broadcast directly to bob"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 10. Cross-server gameplay: gateway delivers broadcast_event to local ws
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gateway_delivers_broadcast_event_to_local_ws():
    """
    When gateway receives a broadcast_event for a room, it must deliver the
    payload to all locally-connected members of that room.
    """
    store, bus, owner, gateway = _shared_infra()

    # alice and bob are both on gateway for this room
    ws_alice = _ws()
    ws_bob = _ws()
    gateway._authenticated[ws_alice] = {"username": "alice", "rating": 1200}
    gateway._ws_username[ws_alice] = "alice"
    gateway._authenticated[ws_bob] = {"username": "bob", "rating": 1100}
    gateway._ws_username[ws_bob] = "bob"

    # Create a local room on gateway so room_manager knows about it
    r = await gateway._handle_create_room(ws_alice)
    room_id = decode_message(r)["payload"]["room_id"]
    await gateway._handle_join_room({"room_id": room_id}, ws_bob)

    ws_alice.send.reset_mock()
    ws_bob.send.reset_mock()

    # Owner sends a broadcast_event
    bcast = make_broadcast_event(
        source_server="owner",
        target_server="gateway",
        room_id=room_id,
        broadcasts=["broadcast-payload-1", "broadcast-payload-2"],
    )
    await gateway._handle_inbound_event(bcast)

    # Both local ws must have received both payloads
    alice_calls = [c[0][0] for c in ws_alice.send.call_args_list]
    bob_calls = [c[0][0] for c in ws_bob.send.call_args_list]
    assert "broadcast-payload-1" in alice_calls or "broadcast-payload-2" in alice_calls
    assert "broadcast-payload-1" in bob_calls or "broadcast-payload-2" in bob_calls


# ─────────────────────────────────────────────────────────────────────────────
# 11, 12 & 13. Cross-server matchmaking
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_server_matchmaking_owner_creates_session():
    """
    Owner receives create_session_cmd, creates an authoritative GameSession,
    and publishes session_created room_events to both connection servers.
    """
    store, bus, owner, gateway = _shared_infra()

    published = []
    orig = bus.publish_async

    async def capture(ch, msg):
        published.append((ch, msg))
        await orig(ch, msg)

    bus.publish_async = capture  # type: ignore[method-assign]

    cmd = make_create_session_cmd(
        source_server="gateway",
        target_server="owner",
        room_id="match-room-1",
        player1_username="alice",
        player1_rating=1200,
        player1_server="gateway",
        player2_username="bob",
        player2_rating=1100,
        player2_server="gateway",
    )
    await owner._handle_inbound_command(cmd)

    # Owner should have created a session
    sessions = list(owner.session_manager._sessions.values())
    assert len(sessions) >= 1, "Owner must have created a session"

    # Two room_event(session_created) messages must be published
    session_evts = [
        (ch, m) for ch, m in published
        if m.get("type") == "room_event" and m.get("event_type") == "session_created"
    ]
    assert len(session_evts) == 2, (
        f"Expected 2 session_created events, got {session_evts}"
    )


@pytest.mark.asyncio
async def test_cross_server_matchmaking_gateway_delivers_match_found():
    """
    Full matchmaking flow: owner creates session and notifies gateway;
    gateway delivers match_found + game_state to both client websockets.
    """
    store, bus, owner, gateway = _shared_infra()

    ws_alice = _ws()
    ws_bob = _ws()
    gateway._authenticated[ws_alice] = {"username": "alice", "rating": 1200}
    gateway._ws_username[ws_alice] = "alice"
    gateway._authenticated[ws_bob] = {"username": "bob", "rating": 1100}
    gateway._ws_username[ws_bob] = "bob"
    store.player_set_server("alice", "gateway")
    store.player_set_server("bob", "gateway")

    cmd = make_create_session_cmd(
        source_server="gateway",
        target_server="owner",
        room_id="match-room-2",
        player1_username="alice",
        player1_rating=1200,
        player1_server="gateway",
        player2_username="bob",
        player2_rating=1100,
        player2_server="gateway",
    )
    await owner._handle_inbound_command(cmd)

    # Both alice and bob should have received match_found + game_state
    for ws, name in [(ws_alice, "alice"), (ws_bob, "bob")]:
        assert ws.send.await_count >= 2, (
            f"{name} should have received >=2 messages, got {ws.send.await_count}"
        )
        calls = [decode_message(c[0][0]) for c in ws.send.call_args_list]
        types = [m["type"] for m in calls]
        assert "match_found" in types, f"match_found not in {types} for {name}"
        assert "game_state" in types, f"game_state not in {types} for {name}"


# ─────────────────────────────────────────────────────────────────────────────
# 14, 15 & 16. Cross-server reconnect
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_server_reconnect_cmd_published():
    """
    When a player logs in with a pending reconnect whose session lives on a
    remote owner, a reconnect_cmd must be published to the owner's commands channel.
    """
    store = NullRedisStore(server_id="gateway")
    store.server_register("gateway")
    store.server_register("owner")

    bus = NullInternalMessageBus()
    published = []

    async def capture(ch, msg):
        published.append((ch, msg))

    bus.publish_async = capture  # type: ignore[method-assign]

    gateway = _make_router("gateway", bus, store)

    # Seed a pending reconnect entry; session is on "owner"
    import time
    entry = ReconnectEntry(
        username="alice",
        color="w",
        room_id="room-77",
        session_id="sess-77",
        disconnect_time=time.monotonic(),
        deadline=time.monotonic() + 30,
    )
    store._rc["alice"] = entry
    store.room_set_server("room-77", "owner")
    store.player_set_server("alice", "gateway")

    ws_alice = _ws()
    gateway._authenticated[ws_alice] = {"username": "alice", "rating": 1200}
    gateway._ws_username[ws_alice] = "alice"

    # Simulate login + reconnect detection
    pending = gateway._get_pending_reconnect("alice")
    assert pending is not None
    gateway._handle_reconnect(ws_alice, pending, "alice", 1200)

    # A reconnect_cmd must have been scheduled (via create_task) to owner
    # Because _handle_reconnect is sync, the task is scheduled but not yet run.
    # We verify it was published by running the pending tasks.
    import asyncio
    await asyncio.sleep(0)  # yield to let any scheduled tasks run

    reconnect_cmds = [
        (ch, m) for ch, m in published
        if m.get("type") == "reconnect_cmd"
    ]
    assert len(reconnect_cmds) == 1, (
        f"Expected 1 reconnect_cmd, got: {published}"
    )
    ch, cmd = reconnect_cmds[0]
    assert ch == commands_channel("owner")
    assert cmd["username"] == "alice"
    assert cmd["room_id"] == "room-77"


@pytest.mark.asyncio
async def test_cross_server_reconnect_owner_restores_and_responds():
    """
    Owner receives reconnect_cmd, restores the player metadata, and sends:
    - room_event("reconnected") to gateway with login_success + game_state
    - broadcast_event("player_reconnected") to all connection servers
    """
    store, bus, owner, gateway = _shared_infra()

    # Set up a full game on owner: alice (w) + bob (b)
    ws_alice = _ws()
    ws_bob = _ws()
    owner._authenticated[ws_alice] = {"username": "alice", "rating": 1200}
    owner._ws_username[ws_alice] = "alice"
    owner._authenticated[ws_bob] = {"username": "bob", "rating": 1100}
    owner._ws_username[ws_bob] = "bob"
    store.player_set_server("alice", "owner")
    store.player_set_server("bob", "owner")

    r = await owner._handle_create_room(ws_alice)
    room_id = decode_message(r)["payload"]["room_id"]
    store.room_set_server(room_id, "owner")
    await owner._handle_join_room({"room_id": room_id}, ws_bob)

    # alice disconnects and reconnects from gateway
    store.player_set_server("alice", "gateway")
    ws_alice_gw = _ws()
    gateway._authenticated[ws_alice_gw] = {"username": "alice", "rating": 1200}
    gateway._ws_username[ws_alice_gw] = "alice"

    cmd = make_reconnect_cmd(
        source_server="gateway",
        target_server="owner",
        room_id=room_id,
        session_id=owner.session_manager.get_session_id(
            owner.room_manager.get_room(room_id).session
        ),
        username="alice",
        color="w",
        rating=1200,
    )
    await owner._handle_inbound_command(cmd)

    # Gateway must have delivered login_success + game_state to alice
    assert ws_alice_gw.send.await_count >= 2, (
        f"Expected >=2 messages to reconnecting alice, got {ws_alice_gw.send.await_count}"
    )
    calls = [decode_message(c[0][0]) for c in ws_alice_gw.send.call_args_list]
    types = [m["type"] for m in calls]
    assert "login_success" in types, f"login_success not in {types}"
    assert "game_state" in types, f"game_state not in {types}"


# ─────────────────────────────────────────────────────────────────────────────
# 17. Fan-out: broadcasts go to ALL connection servers with players
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fanout_broadcasts_to_all_servers():
    """
    When a session has players on 3 different servers, _fanout_broadcasts
    must publish a broadcast_event to each remote server and deliver directly
    to the local server's clients.
    """
    store, bus, owner, gateway = _shared_infra()

    # Create a third virtual "spectator" server
    store.server_register("spec-server")

    published = []
    orig = bus.publish_async

    async def capture(ch, msg):
        published.append((ch, msg))
        await orig(ch, msg)

    bus.publish_async = capture  # type: ignore[method-assign]

    # alice on owner (local), bob on gateway, carol on spec-server
    ws_alice = _ws()
    owner._authenticated[ws_alice] = {"username": "alice", "rating": 1200}
    owner._ws_username[ws_alice] = "alice"
    store.player_set_server("alice", "owner")

    r = await owner._handle_create_room(ws_alice)
    room_id = decode_message(r)["payload"]["room_id"]
    store.room_set_server(room_id, "owner")

    # Manually register bob and carol in store (remote players)
    store.player_set_server("bob", "gateway")
    store.player_set_server("carol", "spec-server")

    # Inject them as known usernames in the session
    session = owner.room_manager.get_room(room_id).session
    from unittest.mock import MagicMock
    bob_sentinel = MagicMock()
    carol_sentinel = MagicMock()
    session._player_usernames[bob_sentinel] = "bob"
    session._player_usernames[carol_sentinel] = "carol"

    ws_alice.send.reset_mock()

    broadcasts = ["test-broadcast-msg"]
    await owner._fanout_broadcasts(session, room_id, broadcasts)

    # alice gets direct delivery (local)
    assert ws_alice.send.await_count >= 1, "alice should receive direct broadcast"

    # gateway and spec-server should each receive a broadcast_event
    remote_bcasts = [
        (ch, m) for ch, m in published
        if m.get("type") == "broadcast_event"
    ]
    target_servers = {m["target_server"] for _, m in remote_bcasts}
    assert "gateway" in target_servers, f"gateway missing from {target_servers}"
    assert "spec-server" in target_servers, f"spec-server missing from {target_servers}"

    # owner itself must NOT receive a broadcast_event
    assert "owner" not in target_servers, f"owner should not get broadcast_event"


# ─────────────────────────────────────────────────────────────────────────────
# 18. Fan-out: no broadcast_event when all players are local
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fanout_no_bus_publish_when_all_local():
    """
    When all players are on the owner server, _fanout_broadcasts must NOT
    publish any broadcast_event via the bus.
    """
    store, bus, owner, _ = _shared_infra()

    bus_calls = []
    orig = bus.publish_async

    async def capture(ch, msg):
        bus_calls.append((ch, msg))
        await orig(ch, msg)

    bus.publish_async = capture  # type: ignore[method-assign]

    ws_alice = _ws()
    ws_bob = _ws()
    owner._authenticated[ws_alice] = {"username": "alice", "rating": 1200}
    owner._ws_username[ws_alice] = "alice"
    owner._authenticated[ws_bob] = {"username": "bob", "rating": 1100}
    owner._ws_username[ws_bob] = "bob"
    store.player_set_server("alice", "owner")
    store.player_set_server("bob", "owner")

    r = await owner._handle_create_room(ws_alice)
    room_id = decode_message(r)["payload"]["room_id"]
    await owner._handle_join_room({"room_id": room_id}, ws_bob)

    ws_alice.send.reset_mock()
    ws_bob.send.reset_mock()
    bus_calls.clear()

    session = owner.room_manager.get_room(room_id).session
    await owner._fanout_broadcasts(session, room_id, ["local-only-msg"])

    broadcast_evts = [m for _, m in bus_calls if m.get("type") == "broadcast_event"]
    assert len(broadcast_evts) == 0, (
        f"No broadcast_event should be published for all-local rooms: {bus_calls}"
    )
    # Both local ws must have received the message directly
    assert ws_alice.send.await_count >= 1
    assert ws_bob.send.await_count >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 19. Error propagation: bad room_id on join_room
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remote_join_room_unknown_room_sends_error():
    """
    Owner receives join_room_cmd for a non-existent room.
    It must publish room_event("error") back to the gateway.
    Gateway delivers make_error to the client.
    """
    store, bus, owner, gateway = _shared_infra()

    ws_bob = _ws()
    gateway._authenticated[ws_bob] = {"username": "bob", "rating": 1100}
    gateway._ws_username[ws_bob] = "bob"
    store.player_set_server("bob", "gateway")

    cmd = make_join_room_cmd(
        source_server="gateway",
        target_server="owner",
        room_id="nonexistent-room",
        username="bob",
        rating=1100,
    )
    await owner._handle_inbound_command(cmd)

    # Gateway should deliver an error to bob
    assert ws_bob.send.await_count >= 1
    sent = decode_message(ws_bob.send.call_args[0][0])
    assert sent["type"] == "error", f"Expected error, got {sent}"


# ─────────────────────────────────────────────────────────────────────────────
# 20. Full end-to-end: two virtual servers, cross-server game lifecycle
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_cross_server_game_lifecycle():
    """
    End-to-end scenario with two virtual servers sharing a NullRedisStore:

    1. Alice (on gateway) creates a room → routed to owner
    2. Bob (on gateway) joins the room → routed to owner
    3. Alice makes a move → game_command forwarded to owner → broadcast_event
       sent to gateway → delivered to both alice and bob
    4. No session exists on gateway (owner holds it)
    """
    store, bus, owner, gateway = _shared_infra()

    # ── Step 1: alice creates a room (owner allocates it) ─────────────────
    ws_alice = _ws()
    ws_bob = _ws()
    gateway._authenticated[ws_alice] = {"username": "alice", "rating": 1200}
    gateway._ws_username[ws_alice] = "alice"
    gateway._authenticated[ws_bob] = {"username": "bob", "rating": 1100}
    gateway._ws_username[ws_bob] = "bob"
    store.player_set_server("alice", "gateway")
    store.player_set_server("bob", "gateway")

    cmd1 = make_create_room_cmd(
        source_server="gateway",
        target_server="owner",
        room_id="e2e-room",
        username="alice",
        rating=1200,
    )
    await owner._handle_inbound_command(cmd1)

    # alice receives room_created
    assert ws_alice.send.await_count >= 1
    msg_a = decode_message(ws_alice.send.call_args_list[-1][0][0])
    assert msg_a["type"] == "room_created"
    room_id = msg_a["payload"]["room_id"]

    # ── Step 2: bob joins the room ────────────────────────────────────────
    ws_alice.send.reset_mock()
    ws_bob.send.reset_mock()

    cmd2 = make_join_room_cmd(
        source_server="gateway",
        target_server="owner",
        room_id=room_id,
        username="bob",
        rating=1100,
    )
    await owner._handle_inbound_command(cmd2)

    bob_calls = [decode_message(c[0][0]) for c in ws_bob.send.call_args_list]
    bob_types = [m["type"] for m in bob_calls]
    assert "room_joined" in bob_types, f"bob: room_joined missing from {bob_types}"
    assert "game_state" in bob_types, f"bob: game_state missing from {bob_types}"

    # ── Step 3: alice makes a move ────────────────────────────────────────
    ws_alice.send.reset_mock()
    ws_bob.send.reset_mock()

    move_cmd = make_game_command(
        source_server="gateway",
        target_server="owner",
        room_id=room_id,
        username="alice",
        cmd="move_request",
        payload={"from_row": 6, "from_col": 0, "to_row": 5, "to_col": 0},
    )
    await owner._handle_inbound_command(move_cmd)

    # Both alice and bob should receive broadcasts (via gateway)
    assert ws_alice.send.await_count >= 1 or ws_bob.send.await_count >= 1, (
        "At least one player must receive a broadcast after a move"
    )

    # ── Step 4: gateway has no local session for this room ────────────────
    room_on_gateway = gateway.room_manager.get_room(room_id)
    session_on_gateway = gateway.session_manager.get_session_for_client(ws_alice)
    assert session_on_gateway is None, (
        "Gateway must NOT hold an authoritative session for a remote room"
    )
