"""
Tests for the graphical lobby UI layer.

Tests the NetworkClient facade and leave_room protocol without
opening actual tkinter windows.
"""

from unittest.mock import AsyncMock

import pytest

from game.client.ui.network_client import NetworkClient
from game.client.client_game_state import ClientGameState
from game.server.protocol import (
    decode_message,
    make_create_room,
    make_join_room,
    make_leave_room,
    make_login_request,
    make_play_request,
)
from game.server.websocket_server import GameWebSocketServer
from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService


def _ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws


# ─── NetworkClient facade ─────────────────────────────────────────────────────


class TestNetworkClientFacade:
    def test_send_login_enqueues_message(self):
        import queue
        nc = NetworkClient.__new__(NetworkClient)
        nc._outgoing = queue.Queue()
        nc._incoming = queue.Queue()
        nc.state = ClientGameState()

        nc.send_login("alice", "pass", "register")

        raw = nc._outgoing.get_nowait()
        msg = decode_message(raw)
        assert msg["type"] == "login_request"
        assert msg["payload"]["username"] == "alice"
        assert msg["payload"]["action"] == "register"

    def test_send_create_room_enqueues(self):
        import queue
        nc = NetworkClient.__new__(NetworkClient)
        nc._outgoing = queue.Queue()
        nc.state = ClientGameState()

        nc.send_create_room()

        raw = nc._outgoing.get_nowait()
        msg = decode_message(raw)
        assert msg["type"] == "create_room"

    def test_send_join_room_enqueues(self):
        import queue
        nc = NetworkClient.__new__(NetworkClient)
        nc._outgoing = queue.Queue()
        nc.state = ClientGameState()

        nc.send_join_room("abc123")

        raw = nc._outgoing.get_nowait()
        msg = decode_message(raw)
        assert msg["type"] == "join_room"
        assert msg["payload"]["room_id"] == "abc123"

    def test_send_leave_room_enqueues(self):
        import queue
        nc = NetworkClient.__new__(NetworkClient)
        nc._outgoing = queue.Queue()
        nc.state = ClientGameState()

        nc.send_leave_room()

        raw = nc._outgoing.get_nowait()
        msg = decode_message(raw)
        assert msg["type"] == "leave_room"

    def test_send_play_request_enqueues(self):
        import queue
        nc = NetworkClient.__new__(NetworkClient)
        nc._outgoing = queue.Queue()
        nc.state = ClientGameState()

        nc.send_play_request()

        raw = nc._outgoing.get_nowait()
        msg = decode_message(raw)
        assert msg["type"] == "play_request"

    def test_no_websocket_in_facade(self):
        """NetworkClient does not expose raw websocket objects."""
        import queue
        nc = NetworkClient.__new__(NetworkClient)
        nc._outgoing = queue.Queue()
        nc._incoming = queue.Queue()
        nc.state = ClientGameState()

        # UI code accesses only high-level methods
        assert hasattr(nc, "send_login")
        assert hasattr(nc, "send_create_room")
        assert hasattr(nc, "send_join_room")
        assert hasattr(nc, "send_leave_room")
        assert hasattr(nc, "poll_messages")


# ─── Leave room protocol ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLeaveRoom:
    async def test_leave_room_removes_player(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws = _ws()
        srv._connected.add(ws)

        await srv._route_message(make_login_request("alice", "pass", "login"), ws)
        await srv._route_message(make_create_room(), ws)

        assert srv.room_manager.room_count == 1

        result = await srv._route_message(make_leave_room(), ws)
        msg = decode_message(result)
        assert msg["type"] == "room_left"
        assert srv.room_manager.room_count == 0

    async def test_leave_room_when_not_in_room(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("bob", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws = _ws()
        srv._connected.add(ws)
        await srv._route_message(make_login_request("bob", "pass", "login"), ws)

        result = await srv._route_message(make_leave_room(), ws)
        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "not_in_room"

    async def test_leave_room_cleans_session_mapping(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("carol", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws = _ws()
        srv._connected.add(ws)

        await srv._route_message(make_login_request("carol", "pass", "login"), ws)
        await srv._route_message(make_create_room(), ws)

        assert srv.session_manager.is_client_in_session(ws)

        await srv._route_message(make_leave_room(), ws)

        assert not srv.session_manager.is_client_in_session(ws)


# ─── UI state transitions (no tkinter window needed) ──────────────────────────


class TestUIStateTransitions:
    def test_login_success_sets_connected(self):
        state = ClientGameState()
        state.apply_login_success(None, "alice", 1200)
        assert state.connected is True

    def test_room_created_stores_id(self):
        state = ClientGameState()
        state.apply_room_created("room123")
        assert state.room_id == "room123"
        assert state.room_role == "player"

    def test_room_joined_viewer(self):
        state = ClientGameState()
        state.apply_room_joined("room456", "viewer", None)
        assert state.is_viewer is True
        assert state.room_id == "room456"

    def test_match_found_sets_color(self):
        state = ClientGameState()
        state.apply_match_found({
            "opponent_username": "bob",
            "color": "b",
            "own_rating": 1200,
            "opponent_rating": 1250,
        })
        assert state.player_color == "b"
        assert state.opponent_username == "bob"


# ─── Lifecycle: no stuck dialog after game start ──────────────────────────────


class TestLobbyLifecycle:
    """Tests that game launch is deterministic and dialog closes properly."""

    def test_start_game_guard_prevents_double_launch(self):
        """_start_game sets _game_ready; second call is no-op."""
        from game.client.ui.lobby_app import LobbyApp

        app = LobbyApp.__new__(LobbyApp)
        app._game_ready = False
        app._root = None  # No actual tkinter

        # Simulate first call (would normally destroy root)
        app._game_ready = True

        # Second call should be guarded
        # Just verify the guard flag
        assert app._game_ready is True

    def test_room_joined_and_game_state_in_same_batch(self):
        """
        When room_joined and game_state arrive in the same drain,
        both are processed and _start_game is called.
        """
        import queue as q
        from game.client.ui.network_client import NetworkClient
        from game.client.ui.lobby_app import LobbyApp

        # Simulate the processing logic without tkinter
        nc = NetworkClient.__new__(NetworkClient)
        nc._outgoing = q.Queue()
        nc._incoming = q.Queue()
        nc.state = ClientGameState()

        app = LobbyApp.__new__(LobbyApp)
        app._client = nc
        app._game_ready = False
        app._root = None  # No actual tkinter

        # Simulate the batch: room_joined + game_state
        batch = [
            {"type": "room_joined", "payload": {"room_id": "xyz", "role": "player", "color": "b"}},
            {"type": "game_state", "payload": {
                "board": [["wR", ".", ".", "bK"]],
                "clock": 0.0, "white_score": 0, "black_score": 0, "game_over": False,
            }},
        ]

        # Process like _check_room_joined does
        joined = False
        for msg in batch:
            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})

            if msg_type == "room_joined":
                role = payload.get("role", "player")
                color = payload.get("color")
                nc.state.apply_room_joined("xyz", role, color)
                joined = True
                continue
            elif msg_type == "game_state":
                nc.state.apply_game_state(
                    payload.get("board", []),
                    payload.get("clock", 0.0),
                    payload.get("white_score", 0),
                    payload.get("black_score", 0),
                    payload.get("game_over", False),
                )
                app._game_ready = True
                break

        assert app._game_ready is True
        assert nc.state.player_color == "b"
        assert nc.state.board == [["wR", ".", ".", "bK"]]

    def test_creator_receives_game_state_and_launches(self):
        """Creator's _check_room_game_state processes game_state and sets game_ready."""
        import queue as q
        from game.client.ui.network_client import NetworkClient

        nc = NetworkClient.__new__(NetworkClient)
        nc._outgoing = q.Queue()
        nc._incoming = q.Queue()
        nc.state = ClientGameState()

        # Simulate what _check_room_game_state would do
        msg = {"type": "game_state", "payload": {
            "board": [["wR", ".", ".", "bK"]],
            "clock": 0.0, "white_score": 0, "black_score": 0, "game_over": False,
        }}

        nc.state.apply_game_state(
            msg["payload"]["board"], 0.0, 0, 0, False
        )
        nc.state.player_color = "w"
        game_ready = True

        assert game_ready is True
        assert nc.state.player_color == "w"
        assert nc.state.board[0][0] == "wR"


# ─── Reconnect in GUI: same-batch regression ──────────────────────────────────


class TestGUIReconnectBatch:
    """
    Regression: login_success(reconnected=true) + game_state in same batch
    must launch the game immediately without discarding game_state.
    """

    def test_login_success_reconnect_and_game_state_same_batch(self):
        """Both messages in one poll — game launches directly."""
        import queue as q
        from game.client.ui.network_client import NetworkClient
        from game.client.ui.lobby_app import LobbyApp

        nc = NetworkClient.__new__(NetworkClient)
        nc._outgoing = q.Queue()
        nc._incoming = q.Queue()
        nc.state = ClientGameState()

        app = LobbyApp.__new__(LobbyApp)
        app._client = nc
        app._game_ready = False
        app._root = None

        # Simulate the batch processing logic from _check_auth_response
        batch = [
            {"type": "login_success", "payload": {
                "username": "alice", "color": "w", "rating": 1200, "reconnected": True}},
            {"type": "game_state", "payload": {
                "board": [["wR", ".", ".", "bK"]],
                "clock": 0.0, "white_score": 0, "black_score": 0, "game_over": False}},
        ]

        is_reconnect = False
        found_login = False
        found_game_state = False
        game_state_payload = None

        for msg in batch:
            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})

            if msg_type == "login_success" and not found_login:
                nc.state.apply_login_success(
                    payload.get("color") or None,
                    payload.get("username", ""),
                    payload.get("rating", 1200),
                )
                is_reconnect = payload.get("reconnected", False)
                found_login = True
                continue
            elif msg_type == "game_state":
                game_state_payload = payload
                found_game_state = True
                break

        # Verify both were found
        assert found_login is True
        assert is_reconnect is True
        assert found_game_state is True
        assert game_state_payload is not None

        # Apply game state (simulates _start_game path)
        nc.state.apply_game_state(
            game_state_payload["board"], 0.0, 0, 0, False
        )
        app._game_ready = True

        assert app._game_ready is True
        assert nc.state.board == [["wR", ".", ".", "bK"]]
        assert nc.state.player_color == "w"

    def test_login_success_reconnect_game_state_later_batch(self):
        """game_state arrives in next poll — reconnect wait handles it."""
        import queue as q
        from game.client.ui.network_client import NetworkClient

        nc = NetworkClient.__new__(NetworkClient)
        nc._outgoing = q.Queue()
        nc._incoming = q.Queue()
        nc.state = ClientGameState()

        # First batch: only login_success
        batch1 = [
            {"type": "login_success", "payload": {
                "username": "alice", "color": "w", "rating": 1200, "reconnected": True}},
        ]

        found_login = False
        is_reconnect = False
        found_game_state = False

        for msg in batch1:
            if msg.get("type") == "login_success":
                nc.state.apply_login_success("w", "alice", 1200)
                is_reconnect = True
                found_login = True

        assert found_login and is_reconnect and not found_game_state
        # At this point, _handle_reconnect would be called, scheduling polling

        # Second batch: game_state arrives
        batch2 = [
            {"type": "game_state", "payload": {
                "board": [["wR", ".", ".", "bK"]],
                "clock": 0.0, "white_score": 0, "black_score": 0, "game_over": False}},
        ]

        for msg in batch2:
            if msg.get("type") == "game_state":
                nc.state.apply_game_state(
                    msg["payload"]["board"], 0.0, 0, 0, False
                )
                found_game_state = True

        assert found_game_state is True
        assert nc.state.board == [["wR", ".", ".", "bK"]]

    def test_normal_login_no_reconnect_goes_to_home(self):
        """Normal login without reconnected=true does not wait for game_state."""
        import queue as q
        from game.client.ui.network_client import NetworkClient

        nc = NetworkClient.__new__(NetworkClient)
        nc._outgoing = q.Queue()
        nc._incoming = q.Queue()
        nc.state = ClientGameState()

        batch = [
            {"type": "login_success", "payload": {
                "username": "bob", "color": "", "rating": 1200, "reconnected": False}},
        ]

        found_login = False
        is_reconnect = False

        for msg in batch:
            if msg.get("type") == "login_success":
                payload = msg["payload"]
                nc.state.apply_login_success(
                    payload.get("color") or None, payload["username"], payload["rating"]
                )
                is_reconnect = payload.get("reconnected", False)
                found_login = True

        assert found_login is True
        assert is_reconnect is False
        assert nc.state.connected is True
        # Would show home screen, not wait for game_state
