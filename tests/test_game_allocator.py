"""
Stage 3 tests: GameAllocator, server registration, ownership enforcement,
active room count, heartbeat/TTL behaviour, and single-server fallback.

All tests use NullRedisStore (no live Redis required) so they run in the
normal pytest suite without infrastructure.

Coverage matrix
───────────────
Allocator unit tests:
  - NullGameAllocator always returns own server_id
  - NullGameAllocator.is_local() always returns True
  - GameAllocator returns own_server_id when store is empty (fallback)
  - GameAllocator picks the server with the lowest active_rooms
  - GameAllocator ignores dead servers (not in store)
  - GameAllocator handles store exception gracefully (fallback)

Server registry (NullRedisStore):
  - server_register creates an entry with 0 active_rooms
  - server_heartbeat updates last_seen
  - server_deregister removes the entry
  - server_list_active returns entries sorted by active_rooms
  - server_increment_rooms and server_decrement_rooms maintain count correctly
  - server_decrement_rooms never goes below 0

Room ownership (router integration):
  - room creation increments active room count on the owning server
  - matchmaking increments active room count on the owning server
  - game end (GameEnded event) decrements active room count
  - double game-end event does NOT double-decrement (guard flag)
  - peer-server allocation records routing metadata but creates no local session

Single-server fallback:
  - GameAllocator with one registered server always picks that server
  - NullGameAllocator always behaves as local owner
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from game.server.game_allocator import GameAllocator, NullGameAllocator
from game.server.redis_store import GameServerInfo, NullRedisStore
from game.server.game_session_manager import GameSessionManager
from game.server.room_manager import RoomManager
from game.server.connection_router import ClientSessionRouter
from game.server.websocket_server import GameWebSocketServer
from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService
from game.server.protocol import (
    decode_message,
    make_create_room,
    make_join_room,
    make_login_request,
    make_play_request,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws


def _store(server_id: str = "server-1") -> NullRedisStore:
    return NullRedisStore(server_id=server_id)


def _registered_store(*server_ids: str) -> NullRedisStore:
    """Return a NullRedisStore with the given servers pre-registered."""
    store = _store(server_ids[0])
    for sid in server_ids:
        store.server_register(sid)
    return store


# ── NullGameAllocator ──────────────────────────────────────────────────────────

class TestNullGameAllocator:
    def test_always_returns_own_server_id(self):
        alloc = NullGameAllocator("my-server")
        assert alloc.allocate_server() == "my-server"

    def test_default_server_id(self):
        alloc = NullGameAllocator()
        assert alloc.allocate_server() == "server-1"

    def test_is_local_always_true(self):
        alloc = NullGameAllocator("any-server")
        assert alloc.is_local("any-server") is True
        assert alloc.is_local("another-server") is True
        assert alloc.is_local("") is True

    def test_own_server_id_property(self):
        alloc = NullGameAllocator("srv-42")
        assert alloc.own_server_id == "srv-42"

    def test_repeated_calls_consistent(self):
        alloc = NullGameAllocator("stable")
        results = {alloc.allocate_server() for _ in range(10)}
        assert results == {"stable"}


# ── GameAllocator — empty registry fallback ────────────────────────────────────

class TestGameAllocatorFallback:
    def test_returns_own_id_when_no_servers_registered(self):
        store = _store("me")
        alloc = GameAllocator(store, own_server_id="me")
        assert alloc.allocate_server() == "me"

    def test_returns_own_id_when_all_servers_deregistered(self):
        store = _registered_store("a", "b")
        store.server_deregister("a")
        store.server_deregister("b")
        alloc = GameAllocator(store, own_server_id="me")
        assert alloc.allocate_server() == "me"

    def test_is_local_true_for_own_id(self):
        alloc = GameAllocator(_store("srv"), own_server_id="srv")
        assert alloc.is_local("srv") is True

    def test_is_local_false_for_other_id(self):
        alloc = GameAllocator(_store("srv"), own_server_id="srv")
        assert alloc.is_local("other") is False

    def test_exception_in_store_falls_back_gracefully(self):
        """If the store raises, allocate_server() returns own_server_id."""
        broken_store = MagicMock()
        broken_store.server_list_active.side_effect = RuntimeError("Redis down")
        alloc = GameAllocator(broken_store, own_server_id="safe")
        assert alloc.allocate_server() == "safe"


# ── GameAllocator — least-loaded selection ─────────────────────────────────────

class TestGameAllocatorLeastLoaded:
    def test_single_registered_server_is_selected(self):
        store = _registered_store("only")
        alloc = GameAllocator(store, own_server_id="only")
        assert alloc.allocate_server() == "only"

    def test_picks_server_with_zero_rooms_over_loaded(self):
        store = _registered_store("light", "heavy")
        store.server_increment_rooms("heavy")
        store.server_increment_rooms("heavy")
        store.server_increment_rooms("heavy")
        alloc = GameAllocator(store, own_server_id="light")
        assert alloc.allocate_server() == "light"

    def test_picks_least_loaded_of_three(self):
        store = _registered_store("s1", "s2", "s3")
        store.server_increment_rooms("s1")   # s1: 1
        store.server_increment_rooms("s1")   # s1: 2
        store.server_increment_rooms("s2")   # s2: 1
        # s3: 0  → should win
        alloc = GameAllocator(store, own_server_id="s1")
        assert alloc.allocate_server() == "s3"

    def test_picks_any_when_all_equal(self):
        store = _registered_store("a", "b")
        # Both at 0 rooms — either is valid
        alloc = GameAllocator(store, own_server_id="a")
        result = alloc.allocate_server()
        assert result in ("a", "b")

    def test_ignores_deregistered_server(self):
        store = _registered_store("live", "dead")
        store.server_deregister("dead")
        alloc = GameAllocator(store, own_server_id="live")
        assert alloc.allocate_server() == "live"

    def test_allocation_changes_after_increment(self):
        """After server A gets a room, server B (with 0) should be preferred."""
        store = _registered_store("a", "b")
        alloc = GameAllocator(store, own_server_id="a")

        first = alloc.allocate_server()   # either; both at 0
        store.server_increment_rooms(first)
        other = "b" if first == "a" else "a"
        assert alloc.allocate_server() == other


# ── NullRedisStore: server registry ───────────────────────────────────────────

class TestNullRedisStoreRegistry:
    def test_register_creates_entry_with_zero_rooms(self):
        store = _store("srv")
        info = store.server_register("srv")
        assert info.server_id == "srv"
        assert info.active_rooms == 0

    def test_register_multiple_servers(self):
        store = _store("s1")
        store.server_register("s1")
        store.server_register("s2")
        active = store.server_list_active()
        ids = {s.server_id for s in active}
        assert ids == {"s1", "s2"}

    def test_list_active_sorted_by_active_rooms(self):
        store = _store("s1")
        store.server_register("s1")
        store.server_register("s2")
        store.server_register("s3")
        store.server_increment_rooms("s1")
        store.server_increment_rooms("s1")
        store.server_increment_rooms("s2")
        active = store.server_list_active()
        counts = [s.active_rooms for s in active]
        assert counts == sorted(counts), "list_active must be sorted by active_rooms"

    def test_heartbeat_updates_last_seen(self):
        store = _store("srv")
        store.server_register("srv")
        before = store.server_get_info("srv").last_seen
        time.sleep(0.01)
        store.server_heartbeat("srv")
        after = store.server_get_info("srv").last_seen
        assert after >= before

    def test_deregister_removes_entry(self):
        store = _store("srv")
        store.server_register("srv")
        assert len(store.server_list_active()) == 1
        store.server_deregister("srv")
        assert len(store.server_list_active()) == 0

    def test_get_info_returns_none_when_not_registered(self):
        store = _store("srv")
        assert store.server_get_info("missing") is None

    def test_increment_rooms(self):
        store = _store("srv")
        store.server_register("srv")
        assert store.server_increment_rooms("srv") == 1
        assert store.server_increment_rooms("srv") == 2
        assert store.server_get_info("srv").active_rooms == 2

    def test_decrement_rooms(self):
        store = _store("srv")
        store.server_register("srv")
        store.server_increment_rooms("srv")
        store.server_increment_rooms("srv")
        assert store.server_decrement_rooms("srv") == 1
        assert store.server_decrement_rooms("srv") == 0

    def test_decrement_never_below_zero(self):
        store = _store("srv")
        store.server_register("srv")
        result = store.server_decrement_rooms("srv")
        assert result == 0
        result2 = store.server_decrement_rooms("srv")
        assert result2 == 0

    def test_increment_on_unknown_server_returns_zero(self):
        """Graceful handling of unregistered server."""
        store = _store("srv")
        result = store.server_increment_rooms("ghost")
        assert result == 0

    def test_list_active_empty_when_nothing_registered(self):
        store = _store("srv")
        assert store.server_list_active() == []


# ── Integration: room creation increments count ───────────────────────────────

@pytest.mark.asyncio
class TestRoomOwnershipIntegration:
    def _make_server(self, server_id: str = "server-1"):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "pass")
        user_svc.register("bob", "pass")

        store = NullRedisStore(server_id=server_id)
        store.server_register(server_id)
        allocator = NullGameAllocator(own_server_id=server_id)

        srv = GameWebSocketServer(
            user_service=user_svc,
            store=store,
            allocator=allocator,
        )
        return srv, store

    async def test_room_creation_increments_room_count(self):
        srv, store = self._make_server()
        ws = _ws()
        srv._connected.add(ws)

        await srv._route_message(make_login_request("alice", "pass", "login"), ws)
        result = await srv._route_message(make_create_room(), ws)

        info = store.server_get_info("server-1")
        assert info is not None
        assert info.active_rooms == 1

    async def test_two_rooms_increment_count_twice(self):
        srv, store = self._make_server()
        ws1, ws2 = _ws(), _ws()
        srv._connected.add(ws1)
        srv._connected.add(ws2)

        await srv._route_message(make_login_request("alice", "pass", "login"), ws1)
        await srv._route_message(make_login_request("bob", "pass", "login"), ws2)
        await srv._route_message(make_create_room(), ws1)
        await srv._route_message(make_create_room(), ws2)

        info = store.server_get_info("server-1")
        assert info.active_rooms == 2

    async def test_room_ownership_stored_in_redis(self):
        srv, store = self._make_server()
        ws = _ws()
        srv._connected.add(ws)

        await srv._route_message(make_login_request("alice", "pass", "login"), ws)
        result = await srv._route_message(make_create_room(), ws)
        room_id = decode_message(result)["payload"]["room_id"]

        # The room_manager uses session_id as the routing key, not room_id.
        # Verify via the room itself.
        room = srv.room_manager.get_room(room_id)
        assert room is not None
        session_id = srv.session_manager.get_session_id(room.session)
        owner = store.room_get_server(session_id)
        assert owner == "server-1"

    async def test_matchmaking_increments_room_count(self):
        srv, store = self._make_server()
        ws1, ws2 = _ws(), _ws()
        srv._connected.add(ws1)
        srv._connected.add(ws2)

        await srv._route_message(make_login_request("alice", "pass", "login"), ws1)
        await srv._route_message(make_login_request("bob", "pass", "login"), ws2)
        await srv._route_message(make_play_request(), ws1)
        await srv._route_message(make_play_request(), ws2)

        # Process matchmaking
        await srv._process_matchmaking()

        info = store.server_get_info("server-1")
        assert info is not None
        assert info.active_rooms == 1

    async def test_game_end_decrements_room_count(self):
        srv, store = self._make_server()
        ws1, ws2 = _ws(), _ws()
        srv._connected.add(ws1)
        srv._connected.add(ws2)

        await srv._route_message(make_login_request("alice", "pass", "login"), ws1)
        await srv._route_message(make_login_request("bob", "pass", "login"), ws2)
        result = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result)["payload"]["room_id"]
        await srv._route_message(make_join_room(room_id), ws2)

        # Confirm count is 1
        assert store.server_get_info("server-1").active_rooms == 1

        # Trigger game end by setting game_over and firing the event
        room = srv.room_manager.get_room(room_id)
        from game.events.engine_events import GameEnded
        from game.model.piece import PieceColor
        room.session.engine.game_over = True
        room.session.engine.event_bus.publish(
            GameEnded(winner=PieceColor.WHITE, loser=PieceColor.BLACK)
        )

        # Count must drop to 0
        assert store.server_get_info("server-1").active_rooms == 0

    async def test_double_game_end_does_not_double_decrement(self):
        """Guard flag must prevent count from going negative."""
        srv, store = self._make_server()
        ws1, ws2 = _ws(), _ws()
        srv._connected.add(ws1)
        srv._connected.add(ws2)

        await srv._route_message(make_login_request("alice", "pass", "login"), ws1)
        await srv._route_message(make_login_request("bob", "pass", "login"), ws2)
        result = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result)["payload"]["room_id"]
        await srv._route_message(make_join_room(room_id), ws2)

        room = srv.room_manager.get_room(room_id)
        from game.events.engine_events import GameEnded
        from game.model.piece import PieceColor
        evt = GameEnded(winner=PieceColor.WHITE, loser=PieceColor.BLACK)
        room.session.engine.game_over = True
        room.session.engine.event_bus.publish(evt)
        room.session.engine.event_bus.publish(evt)  # duplicate

        assert store.server_get_info("server-1").active_rooms == 0


# ── Integration: peer-server allocation (no local session) ────────────────────

@pytest.mark.asyncio
class TestPeerServerAllocation:
    """
    Verify that when the allocator returns a peer server_id, the router
    records routing metadata but does NOT create a local GameSession.
    """

    def _make_router_with_peer_allocator(self, peer_id: str = "peer-server"):
        """Router whose allocator always picks a remote peer."""
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "pass")

        store = NullRedisStore(server_id="local-server")
        store.server_register("local-server")
        store.server_register(peer_id)
        store.server_increment_rooms("local-server")
        store.server_increment_rooms("local-server")
        store.server_increment_rooms("local-server")
        # peer has 0 rooms → will be selected

        allocator = GameAllocator(store, own_server_id="local-server")
        sm = GameSessionManager()
        room_mgr = RoomManager(sm)
        router = ClientSessionRouter(
            user_service=user_svc,
            session_manager=sm,
            room_manager=room_mgr,
            store=store,
            allocator=allocator,
        )
        return router, store

    async def test_peer_allocation_no_local_session_created(self):
        """
        Stage 5: when allocation picks a remote peer, _handle_create_room
        publishes a create_room_cmd to the bus and returns None (async
        response path).  No local session is created.
        """
        from game.server.internal_bus import NullInternalMessageBus, commands_channel

        bus = NullInternalMessageBus()
        published = []

        async def capture(channel, msg):
            published.append((channel, msg))

        bus.publish_async = capture  # type: ignore[method-assign]

        router, store = self._make_router_with_peer_allocator("peer")
        router._bus = bus

        ws = _ws()
        router._authenticated[ws] = {"username": "alice", "rating": 1200}
        router._ws_username[ws] = "alice"

        result = await router._handle_create_room(ws)

        # Stage 5: remote path returns None; room_created arrives async via bus
        assert result is None

        # A create_room_cmd must have been published to the peer's commands channel
        assert len(published) == 1
        channel, cmd = published[0]
        assert channel == commands_channel("peer")
        assert cmd["type"] == "create_room_cmd"
        assert cmd["username"] == "alice"

        # No local session should exist for alice
        session = router.session_manager.get_session_for_client(ws)
        assert session is None

    async def test_peer_allocation_stores_routing_metadata(self):
        """
        Stage 5: when allocation picks a remote peer, the player→server
        metadata is stored so the bus callback can deliver room_created.
        The room_id is carried in the published create_room_cmd.
        """
        from game.server.internal_bus import NullInternalMessageBus, commands_channel

        bus = NullInternalMessageBus()
        published = []

        async def capture(channel, msg):
            published.append((channel, msg))

        bus.publish_async = capture  # type: ignore[method-assign]

        router, store = self._make_router_with_peer_allocator("peer")
        router._bus = bus

        ws = _ws()
        router._authenticated[ws] = {"username": "alice", "rating": 1200}
        router._ws_username[ws] = "alice"

        await router._handle_create_room(ws)

        # The room_id was assigned before publishing the cmd
        assert len(published) == 1
        _, cmd = published[0]
        room_id = cmd["room_id"]
        assert room_id, "room_id must be non-empty"

        # player→server metadata must point to local-server (gateway side)
        alice_server = store.player_get_server("alice")
        assert alice_server == "local-server"

        # NOTE: room→server metadata is NOT stored on the gateway at this point;
        # it is written by the owner in _owner_handle_create_room and then
        # delivered back via room_event("room_created").
        # The gateway side stores it in _handle_inbound_room_event.

    async def test_local_allocation_creates_session(self):
        """Sanity: with NullGameAllocator (always local), session IS created."""
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "pass")

        store = NullRedisStore(server_id="local")
        store.server_register("local")
        allocator = NullGameAllocator("local")
        sm = GameSessionManager()
        room_mgr = RoomManager(sm)
        router = ClientSessionRouter(
            user_service=user_svc,
            session_manager=sm,
            room_manager=room_mgr,
            store=store,
            allocator=allocator,
        )
        ws = _ws()
        router._authenticated[ws] = {"username": "alice", "rating": 1200}
        router._ws_username[ws] = "alice"

        result = await router._handle_create_room(ws)
        msg = decode_message(result)
        assert msg["type"] == "room_created"

        # Session was assigned to alice's websocket
        session = router.session_manager.get_session_for_client(ws)
        assert session is not None


# ── Single-server fallback end-to-end ─────────────────────────────────────────

@pytest.mark.asyncio
class TestSingleServerFallback:
    """
    Full server flow with NullGameAllocator — mirrors the standard test setup
    to confirm Stage 3 code does not break single-server behaviour.
    """

    def _make_server(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "pass")
        user_svc.register("bob", "pass")
        return GameWebSocketServer(user_service=user_svc)

    async def test_room_flow_still_works(self):
        srv = self._make_server()
        ws1, ws2 = _ws(), _ws()
        srv._connected.add(ws1)
        srv._connected.add(ws2)

        await srv._route_message(make_login_request("alice", "pass", "login"), ws1)
        await srv._route_message(make_login_request("bob", "pass", "login"), ws2)

        result = await srv._route_message(make_create_room(), ws1)
        msg = decode_message(result)
        assert msg["type"] == "room_created"
        room_id = msg["payload"]["room_id"]

        result2 = await srv._route_message(make_join_room(room_id), ws2)
        msgs = result2 if isinstance(result2, list) else [result2]
        types = [decode_message(m)["type"] for m in msgs]
        assert "room_joined" in types

    async def test_matchmaking_flow_still_works(self):
        srv = self._make_server()
        ws1, ws2 = _ws(), _ws()
        srv._connected.add(ws1)
        srv._connected.add(ws2)

        from game.server.protocol import make_login_request as mlr
        await srv._route_message(mlr("alice", "pass", "login"), ws1)
        await srv._route_message(mlr("bob", "pass", "login"), ws2)
        await srv._route_message(make_play_request(), ws1)
        await srv._route_message(make_play_request(), ws2)

        await srv._process_matchmaking()

        assert srv.session_manager.active_session_count == 1
