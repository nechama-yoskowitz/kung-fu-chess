"""
Focused tests for network client bugs:
- Selection must use current board state (not stale initial state)
- ClientGameState.board updates on move_resolved
- Yellow border clears when selected cell becomes empty
- Move history is updated from authoritative move_resolved
"""

import queue
from unittest.mock import MagicMock

from game.client.client_game_state import ClientGameState
from game.client.network_game_gateway import NetworkGameGateway
from game.client.server_message_processor import ServerMessageProcessor
from game.controller.controller import Controller
from game.controller.game_gateway import MoveRequestResult
from game.events import EventBus
from game.events.engine_events import MoveResolved
from game.graphics.graphics_manager import GraphicsManager
from game.history.move_history_observer import MoveHistoryObserver
from game.model.board_mapper import BoardMapper


def make_state_with_board(board, player_color="w"):
    state = ClientGameState()
    state.board = [row[:] for row in board]
    state.player_color = player_color
    state.connected = True
    return state


def make_gateway_and_controller(state):
    outgoing = queue.Queue()
    gateway = NetworkGameGateway(state, outgoing)
    mapper = BoardMapper(cell_width=100, cell_height=100)
    controller = Controller(gateway=gateway, board_mapper=mapper)
    return gateway, controller, outgoing


def make_processor(state, gm=None, event_bus=None):
    if gm is None:
        gm = MagicMock(spec=GraphicsManager)
        gm.graphic_pieces = []
        gm.get_piece_at.return_value = None
    return ServerMessageProcessor(
        state=state,
        graphics_manager=gm,
        event_bus=event_bus,
    )


class TestSelectionUsesCurrentBoard:
    """Selection must read from current authoritative board."""

    def test_white_selects_piece_in_starting_row(self):
        board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wP", ".", ".", ".", ".", ".", ".", "."],
            ["wR", ".", ".", ".", ".", ".", ".", "."],
        ]
        state = make_state_with_board(board, "w")
        _, controller, _ = make_gateway_and_controller(state)

        controller.click(50, 750)  # (7, 0) = wR
        assert controller.selected == (7, 0)

    def test_white_selects_piece_moved_to_middle(self):
        """After a piece moves to the middle, it should still be selectable."""
        board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wR", ".", ".", ".", ".", ".", ".", "."],  # wR moved to row 3
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wP", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
        ]
        state = make_state_with_board(board, "w")
        _, controller, _ = make_gateway_and_controller(state)

        controller.click(50, 350)  # (3, 0) = wR in middle
        assert controller.selected == (3, 0)

    def test_empty_source_not_selectable(self):
        """After a piece leaves, its old cell cannot be selected."""
        board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wR", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],  # (7,0) is empty now
        ]
        state = make_state_with_board(board, "w")
        _, controller, _ = make_gateway_and_controller(state)

        controller.click(50, 750)  # (7, 0) = empty
        assert controller.selected is None

    def test_opponent_piece_not_selectable(self):
        board = [
            ["bR", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wR", ".", ".", ".", ".", ".", ".", "."],
        ]
        state = make_state_with_board(board, "w")
        _, controller, _ = make_gateway_and_controller(state)

        controller.click(50, 50)  # (0, 0) = bR — opponent
        assert controller.selected is None

    def test_black_selects_own_piece_in_middle(self):
        board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", "bN", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
        ]
        state = make_state_with_board(board, "b")
        _, controller, _ = make_gateway_and_controller(state)

        controller.click(150, 350)  # (3, 1) = bN
        assert controller.selected == (3, 1)


class TestYellowBorderClearsAfterResolution:
    """Selection auto-clears when the board changes under it."""

    def test_selection_clears_when_cell_becomes_empty(self):
        board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wR", ".", ".", ".", ".", ".", ".", "."],
        ]
        state = make_state_with_board(board, "w")
        _, controller, _ = make_gateway_and_controller(state)

        # Select wR at (7, 0)
        controller.click(50, 750)
        assert controller.selected == (7, 0)

        # Simulate board update: piece moved away
        state.board[7][0] = "."
        state.board[3][0] = "wR"

        # Now selected should auto-clear
        assert controller.selected is None

    def test_selection_clears_when_cell_becomes_opponent(self):
        board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wR", ".", ".", ".", ".", ".", ".", "."],
        ]
        state = make_state_with_board(board, "w")
        _, controller, _ = make_gateway_and_controller(state)

        controller.click(50, 750)
        assert controller.selected == (7, 0)

        # An opponent captured and landed there
        state.board[7][0] = "bQ"

        assert controller.selected is None


class TestBoardStateUpdatesOnMoveResolved:
    """ClientGameState.board is updated correctly by move_resolved."""

    def test_arrived_clears_source_places_destination(self):
        state = ClientGameState()
        state.board = [["wR", ".", ".", "."]]
        state.player_color = "w"

        state.apply_move_resolved(
            from_row=0, from_col=0,
            piece="wR", outcome="arrived",
            final_row=0, final_col=2,
            promoted_to=None,
        )

        assert state.board[0][0] == "."
        assert state.board[0][2] == "wR"

    def test_captured_mover_removed(self):
        state = ClientGameState()
        state.board = [["wR", ".", "bP", "."]]
        state.player_color = "w"

        state.apply_move_resolved(
            from_row=0, from_col=0,
            piece="wR", outcome="captured",
            final_row=None, final_col=None,
            promoted_to=None,
        )

        # Source cleared, no placement
        assert state.board[0][0] == "."
        assert state.board[0][2] == "bP"  # bP unchanged

    def test_promotion_updates_piece_token(self):
        state = ClientGameState()
        state.board = [[".", ".", ".", "."], ["wP", ".", ".", "."]]
        state.player_color = "w"

        state.apply_move_resolved(
            from_row=1, from_col=0,
            piece="wP", outcome="arrived",
            final_row=0, final_col=0,
            promoted_to="wQ",
        )

        assert state.board[1][0] == "."
        assert state.board[0][0] == "wQ"

    def test_normal_capture_places_mover(self):
        """Normal capture: mover arrives at destination replacing enemy."""
        state = ClientGameState()
        state.board = [["wR", ".", "bR", "."]]
        state.player_color = "w"

        state.apply_move_resolved(
            from_row=0, from_col=0,
            piece="wR", outcome="arrived",
            final_row=0, final_col=2,
            promoted_to=None,
        )

        assert state.board[0][0] == "."
        assert state.board[0][2] == "wR"


class TestProcessorUpdatesBoardState:
    """ServerMessageProcessor updates ClientGameState.board on move_resolved."""

    def test_move_accepted_then_resolved_updates_board(self):
        state = ClientGameState()
        state.board = [["wR", ".", ".", "."]]
        state.player_color = "w"
        state.connected = True

        processor = make_processor(state)

        # Simulate move_accepted
        processor.process_messages([{
            "type": "move_accepted",
            "payload": {
                "sequence_id": 1,
                "piece": "wR",
                "from_row": 0, "from_col": 0,
                "to_row": 0, "to_col": 2,
                "started_at": 0, "arrive_at": 1000,
            }
        }])

        # Simulate move_resolved
        processor.process_messages([{
            "type": "move_resolved",
            "payload": {
                "sequence_id": 1,
                "piece": "wR",
                "outcome": "arrived",
                "final_row": 0, "final_col": 2,
                "promoted_to": None,
                "captured_piece": None,
            }
        }])

        assert state.board[0][0] == "."
        assert state.board[0][2] == "wR"

    def test_captured_mover_clears_source_no_placement(self):
        state = ClientGameState()
        state.board = [["wR", ".", "bP", "."]]
        state.player_color = "w"
        state.connected = True

        processor = make_processor(state)

        processor.process_messages([{
            "type": "move_accepted",
            "payload": {
                "sequence_id": 2,
                "piece": "wR",
                "from_row": 0, "from_col": 0,
                "to_row": 0, "to_col": 2,
                "started_at": 0, "arrive_at": 1000,
            }
        }])

        processor.process_messages([{
            "type": "move_resolved",
            "payload": {
                "sequence_id": 2,
                "piece": "wR",
                "outcome": "captured",
                "final_row": None, "final_col": None,
                "promoted_to": None,
                "captured_piece": "wR",
            }
        }])

        assert state.board[0][0] == "."
        assert state.board[0][2] == "bP"  # bP survives


class TestNetworkMoveHistory:
    """Move history is updated from authoritative move_resolved messages."""

    def test_resolved_creates_one_entry(self):
        bus = EventBus()
        history = MoveHistoryObserver(event_bus=bus, clock_provider=lambda: 5000.0)

        bus.publish(MoveResolved(
            sequence_id=1, piece="wR", outcome="arrived",
            final_row=0, final_col=2,
            promoted_to=None, captured_piece=None,
        ))

        assert len(history.white_moves) == 1
        assert "Rook" in history.white_moves[0]["move"]

    def test_request_alone_creates_no_entry(self):
        """Only resolved moves appear in history, not requests."""
        state = ClientGameState()
        state.board = [["wR", ".", ".", "."]]
        state.player_color = "w"
        state.connected = True

        bus = EventBus()
        history = MoveHistoryObserver(event_bus=bus, clock_provider=lambda: 0.0)
        outgoing = queue.Queue()
        gateway = NetworkGameGateway(state, outgoing)

        # Make a move request (sends to server)
        gateway.request_move(0, 0, 0, 2)

        assert len(history.white_moves) == 0
        assert len(history.black_moves) == 0

    def test_rejected_move_no_success_entry(self):
        """A move_rejected message does not create a history entry."""
        state = ClientGameState()
        state.board = [["wR", ".", ".", "."]]
        state.player_color = "w"
        state.connected = True

        bus = EventBus()
        history = MoveHistoryObserver(event_bus=bus, clock_provider=lambda: 0.0)
        processor = make_processor(state, event_bus=bus)

        processor.process_messages([{
            "type": "move_rejected",
            "payload": {"reason": "not_your_piece", "from_row": 0, "from_col": 0,
                        "to_row": 0, "to_col": 2}
        }])

        assert len(history.white_moves) == 0
        assert len(history.black_moves) == 0

    def test_duplicate_resolved_does_not_duplicate_history(self):
        bus = EventBus()
        history = MoveHistoryObserver(event_bus=bus, clock_provider=lambda: 1000.0)

        event = MoveResolved(
            sequence_id=5, piece="bP", outcome="arrived",
            final_row=3, final_col=0,
            promoted_to=None, captured_piece=None,
        )

        bus.publish(event)
        bus.publish(event)

        assert len(history.black_moves) == 1

    def test_capture_includes_captured_piece(self):
        bus = EventBus()
        history = MoveHistoryObserver(event_bus=bus, clock_provider=lambda: 2000.0)

        bus.publish(MoveResolved(
            sequence_id=10, piece="wR", outcome="arrived",
            final_row=0, final_col=3,
            promoted_to=None, captured_piece="bN",
        ))

        assert len(history.white_moves) == 1
        assert "Knight" in history.white_moves[0]["move"]

    def test_processor_publishes_for_history(self):
        """ServerMessageProcessor triggers history via EventBus."""
        state = ClientGameState()
        state.board = [["wR", ".", ".", "."]]
        state.player_color = "w"
        state.connected = True

        bus = EventBus()
        history = MoveHistoryObserver(event_bus=bus, clock_provider=lambda: 3000.0)
        processor = make_processor(state, event_bus=bus)

        processor.process_messages([{
            "type": "move_accepted",
            "payload": {
                "sequence_id": 7,
                "piece": "wR",
                "from_row": 0, "from_col": 0,
                "to_row": 0, "to_col": 3,
                "started_at": 0, "arrive_at": 1000,
            }
        }])
        processor.process_messages([{
            "type": "move_resolved",
            "payload": {
                "sequence_id": 7,
                "piece": "wR",
                "outcome": "arrived",
                "final_row": 0, "final_col": 3,
                "promoted_to": None,
                "captured_piece": None,
            }
        }])

        assert len(history.white_moves) == 1
