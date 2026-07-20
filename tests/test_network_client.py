"""
Tests for client-side networking: ClientGameState, NetworkGameGateway, NetworkTransport.
"""

import json
import queue
import time
import threading

import pytest

from game.client.client_game_state import ClientGameState
from game.client.network_game_gateway import NetworkGameGateway
from game.client.network_transport import NetworkTransport
from game.controller.game_gateway import MoveRequestResult
from game.server.protocol import decode_message


# ─── ClientGameState ──────────────────────────────────────────────────────────


class TestClientGameStateDefaults:
    def test_default_board_is_8x8_empty(self):
        state = ClientGameState()
        assert len(state.board) == 8
        assert all(len(row) == 8 for row in state.board)
        assert all(cell == "." for row in state.board for cell in row)

    def test_default_scores_zero(self):
        state = ClientGameState()
        assert state.white_score == 0
        assert state.black_score == 0

    def test_default_not_game_over(self):
        state = ClientGameState()
        assert state.game_over is False

    def test_default_no_player_color(self):
        state = ClientGameState()
        assert state.player_color is None


class TestClientGameStatePlayerAssigned:
    def test_apply_player_assigned(self):
        state = ClientGameState()
        state.apply_player_assigned("w")
        assert state.player_color == "w"
        assert state.connected is True

    def test_apply_black(self):
        state = ClientGameState()
        state.apply_player_assigned("b")
        assert state.player_color == "b"


class TestClientGameStateGameState:
    def test_apply_game_state_replaces_board(self):
        state = ClientGameState()
        board = [["wR", ".", ".", "bK"]]
        state.apply_game_state(board, 5000.0, 3, 1, False)
        assert state.board == [["wR", ".", ".", "bK"]]

    def test_apply_game_state_updates_scores(self):
        state = ClientGameState()
        state.apply_game_state([["."]], 100.0, 7, 2, False)
        assert state.white_score == 7
        assert state.black_score == 2

    def test_apply_game_state_updates_clock(self):
        state = ClientGameState()
        state.apply_game_state([["."]], 12345.0, 0, 0, False)
        assert state.clock == 12345.0

    def test_apply_game_state_updates_game_over(self):
        state = ClientGameState()
        state.apply_game_state([["."]], 0.0, 0, 0, True)
        assert state.game_over is True

    def test_defensive_copy(self):
        state = ClientGameState()
        board = [["wR", "."]]
        state.apply_game_state(board, 0.0, 0, 0, False)
        board[0][0] = "bQ"  # mutate original
        assert state.board[0][0] == "wR"  # state unaffected


# ─── NetworkGameGateway ───────────────────────────────────────────────────────


class TestNetworkGameGatewayMoveRequest:
    def test_move_request_queues_protocol_message(self):
        state = ClientGameState()
        state.apply_game_state(
            [["wR", ".", ".", "."]], 0.0, 0, 0, False
        )
        outgoing = queue.Queue()
        gw = NetworkGameGateway(state, outgoing)

        gw.request_move(0, 0, 0, 2)

        msg_raw = outgoing.get_nowait()
        msg = decode_message(msg_raw)
        assert msg["type"] == "move_request"
        assert msg["payload"]["from_row"] == 0
        assert msg["payload"]["to_col"] == 2

    def test_move_request_returns_pending(self):
        state = ClientGameState()
        state.apply_game_state([["wR", ".", "."]], 0.0, 0, 0, False)
        outgoing = queue.Queue()
        gw = NetworkGameGateway(state, outgoing)

        result = gw.request_move(0, 0, 0, 2)

        assert result.is_accepted is False
        assert result.reason == "pending"

    def test_move_request_does_not_mutate_board(self):
        state = ClientGameState()
        state.apply_game_state([["wR", ".", "."]], 0.0, 0, 0, False)
        outgoing = queue.Queue()
        gw = NetworkGameGateway(state, outgoing)

        gw.request_move(0, 0, 0, 2)

        assert state.board[0][0] == "wR"
        assert state.board[0][2] == "."


class TestNetworkGameGatewayJumpRequest:
    def test_jump_request_queues_message(self):
        state = ClientGameState()
        state.apply_game_state([["wR", "."]], 0.0, 0, 0, False)
        outgoing = queue.Queue()
        gw = NetworkGameGateway(state, outgoing)

        gw.request_jump(0, 0)

        msg_raw = outgoing.get_nowait()
        msg = decode_message(msg_raw)
        assert msg["type"] == "jump_request"
        assert msg["payload"]["row"] == 0

    def test_jump_request_returns_false(self):
        state = ClientGameState()
        state.apply_game_state([["wR"]], 0.0, 0, 0, False)
        outgoing = queue.Queue()
        gw = NetworkGameGateway(state, outgoing)

        result = gw.request_jump(0, 0)
        assert result is False


class TestNetworkGameGatewayBoardAccess:
    def test_board_reads_from_client_state(self):
        state = ClientGameState()
        state.apply_game_state([["bK", "wR"]], 0.0, 0, 0, False)
        outgoing = queue.Queue()
        gw = NetworkGameGateway(state, outgoing)

        assert gw.board[0][0] == "bK"
        assert gw.board[0][1] == "wR"


# ─── NetworkTransport ─────────────────────────────────────────────────────────


class TestTransportQueues:
    def test_outgoing_queue_preserves_order(self):
        outgoing = queue.Queue()
        outgoing.put("msg1")
        outgoing.put("msg2")
        assert outgoing.get() == "msg1"
        assert outgoing.get() == "msg2"

    def test_incoming_queue_preserves_order(self):
        incoming = queue.Queue()
        incoming.put({"type": "a"})
        incoming.put({"type": "b"})

        outgoing = queue.Queue()
        transport = NetworkTransport("ws://fake:9999", outgoing, incoming)

        messages = transport.drain_incoming()
        assert messages == [{"type": "a"}, {"type": "b"}]

    def test_drain_incoming_empties_queue(self):
        incoming = queue.Queue()
        incoming.put({"type": "x"})
        outgoing = queue.Queue()
        transport = NetworkTransport("ws://fake:9999", outgoing, incoming)

        transport.drain_incoming()
        assert transport.drain_incoming() == []


class TestTransportConnectionFailure:
    def test_connection_refused_sets_error(self):
        outgoing = queue.Queue()
        incoming = queue.Queue()
        transport = NetworkTransport("ws://localhost:19999", outgoing, incoming)

        transport.start()
        # Wait for the thread to fully complete (connection fail + cleanup)
        transport._thread.join(timeout=5.0)

        assert transport.connected is False
        assert transport.error is not None


class TestTransportCleanShutdown:
    def test_stop_terminates_thread(self):
        outgoing = queue.Queue()
        incoming = queue.Queue()
        transport = NetworkTransport("ws://localhost:19999", outgoing, incoming)

        transport.start()
        # Wait for connection to fail naturally, then stop
        transport._thread.join(timeout=5.0)
        transport.stop(timeout=1.0)

        assert not transport._thread.is_alive()


class TestTransportWithServer:
    """Integration: transport receives messages from a real server."""

    def test_receives_player_assigned_and_game_state(self):
        """Start a real server, connect transport, send login, receive messages."""
        import asyncio
        from game.server.websocket_server import GameWebSocketServer
        from game.server.protocol import make_login_request

        server_ready = threading.Event()
        server_port = [0]

        async def run_test_server():
            srv = GameWebSocketServer(host="localhost", port=0)
            await srv.start()
            server_port[0] = srv._server.sockets[0].getsockname()[1]
            server_ready.set()
            await asyncio.sleep(3)
            await srv.stop()

        server_thread = threading.Thread(
            target=lambda: asyncio.run(run_test_server()),
            daemon=True,
        )
        server_thread.start()
        server_ready.wait(timeout=5)

        # Connect transport and queue a login message
        outgoing = queue.Queue()
        incoming = queue.Queue()
        uri = f"ws://localhost:{server_port[0]}"
        outgoing.put_nowait(make_login_request("TestPlayer"))
        transport = NetworkTransport(uri, outgoing, incoming)
        transport.start()

        # Wait for messages to arrive
        messages = []
        for _ in range(40):  # up to 4 seconds
            time.sleep(0.1)
            messages.extend(transport.drain_incoming())
            if len(messages) >= 2:
                break
        transport.stop(timeout=3.0)

        # Should have received login_success + game_state
        types = [m.get("type") for m in messages]
        assert "login_success" in types
        assert "game_state" in types

    def test_game_state_can_update_client_state(self):
        """Received game_state updates ClientGameState on the game thread."""
        state = ClientGameState()

        # Simulate receiving a game_state message
        incoming_msg = {
            "type": "game_state",
            "payload": {
                "board": [["wR", ".", ".", "bK"]],
                "clock": 1234.0,
                "white_score": 5,
                "black_score": 2,
                "game_over": False,
            },
        }

        # Process on game thread
        payload = incoming_msg["payload"]
        state.apply_game_state(
            payload["board"], payload["clock"],
            payload["white_score"], payload["black_score"],
            payload["game_over"],
        )

        assert state.board == [["wR", ".", ".", "bK"]]
        assert state.white_score == 5
