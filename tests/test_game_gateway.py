"""
Tests for GameCommandGateway abstraction and LocalGameGateway.

Verifies that the Controller is decoupled from GameEngine and that
LocalGameGateway preserves all existing local behavior.
"""

from unittest.mock import MagicMock

from game.controller.controller import Controller
from game.controller.game_gateway import GameCommandGateway, MoveRequestResult
from game.controller.local_game_gateway import LocalGameGateway
from game.engine.game_engine import GameEngine
from game.model.board_mapper import BoardMapper
from game.model.constants import MOVE_DURATION_MS


class TestLocalGameGatewayMoveRequest:
    """LocalGameGateway delegates move requests to the engine."""

    def test_accepted_move(self):
        board = [
            ["wR", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        engine = GameEngine(board)
        gateway = LocalGameGateway(engine)

        result = gateway.request_move(0, 0, 0, 2)

        assert result.is_accepted is True
        assert result.reason == "ok"

    def test_rejected_move(self):
        board = [
            ["wR", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        engine = GameEngine(board)
        gateway = LocalGameGateway(engine)

        # Can't move from empty cell
        result = gateway.request_move(1, 1, 1, 2)

        assert result.is_accepted is False
        assert result.reason != ""


class TestLocalGameGatewayJumpRequest:
    """LocalGameGateway delegates jump requests to the engine."""

    def test_accepted_jump(self):
        board = [
            ["wR", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        engine = GameEngine(board)
        gateway = LocalGameGateway(engine)

        result = gateway.request_jump(0, 0)

        assert result is True

    def test_rejected_jump_empty_cell(self):
        board = [
            ["wR", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        engine = GameEngine(board)
        gateway = LocalGameGateway(engine)

        result = gateway.request_jump(1, 1)

        assert result is False


class TestLocalGameGatewayBoardAccess:
    """LocalGameGateway exposes engine board and piece state."""

    def test_board_property(self):
        board = [["wR", ".", ".", "."]]
        engine = GameEngine(board)
        gateway = LocalGameGateway(engine)

        assert gateway.board[0][0] == "wR"
        assert gateway.board[0][1] == "."

    def test_is_piece_moving_at(self):
        board = [["wR", ".", ".", "."]]
        engine = GameEngine(board)
        gateway = LocalGameGateway(engine)

        engine.request_move(0, 0, 0, 2)

        assert gateway.is_piece_moving_at(0, 0) is True
        assert gateway.is_piece_moving_at(0, 1) is False

    def test_is_piece_resting_at(self):
        board = [["wR", ".", ".", "."]]
        engine = GameEngine(board)
        gateway = LocalGameGateway(engine)

        engine.request_move(0, 0, 0, 2)
        engine.handle_wait(2 * MOVE_DURATION_MS + 1)

        # After arrival, piece enters cooldown
        assert gateway.is_piece_resting_at(0, 2) is True


class TestControllerUsesGateway:
    """Controller uses the gateway rather than directly calling GameEngine."""

    def test_controller_with_gateway(self):
        board = [
            ["wR", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
        ]
        engine = GameEngine(board)
        gateway = LocalGameGateway(engine)
        mapper = BoardMapper(cell_width=100, cell_height=100)

        controller = Controller(gateway=gateway, board_mapper=mapper)

        # First click: select wR at (0, 0)
        controller.click(50, 50)
        assert controller.selected == (0, 0)

        # Second click: move to (0, 2)
        result = controller.click(250, 50)
        assert result is True
        assert len(engine.pending_moves) == 1

    def test_controller_with_mock_gateway(self):
        """Controller works with any gateway implementation."""
        mock_gw = MagicMock(spec=GameCommandGateway)
        mock_gw.board = [
            ["wR", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        mock_gw.player_color = None
        mock_gw.is_piece_moving_at.return_value = False
        mock_gw.is_piece_resting_at.return_value = False
        mock_gw.request_move.return_value = MoveRequestResult(
            is_accepted=True, reason="ok"
        )

        mapper = BoardMapper(cell_width=100, cell_height=100)
        controller = Controller(gateway=mock_gw, board_mapper=mapper)

        # Select piece at (0,0), then move to (0,2)
        controller.click(50, 50)
        result = controller.click(250, 50)

        assert result is True
        mock_gw.request_move.assert_called_once_with(0, 0, 0, 2)

    def test_controller_jump_uses_gateway(self):
        mock_gw = MagicMock(spec=GameCommandGateway)
        mock_gw.board = [["wR", ".", ".", "."]]
        mock_gw.player_color = None
        mock_gw.request_jump.return_value = True

        mapper = BoardMapper(cell_width=100, cell_height=100)
        controller = Controller(gateway=mock_gw, board_mapper=mapper)

        result = controller.jump(50, 50)

        assert result is True
        mock_gw.request_jump.assert_called_once_with(0, 0)


class TestControllerBackwardCompatibility:
    """Controller still works with engine= parameter (legacy)."""

    def test_engine_param_wraps_in_local_gateway(self):
        board = [["wR", ".", ".", "."]]
        engine = GameEngine(board)
        mapper = BoardMapper(cell_width=100, cell_height=100)

        controller = Controller(engine=engine, board_mapper=mapper)

        # Select and move
        controller.click(50, 50)
        result = controller.click(250, 50)

        assert result is True
        assert len(engine.pending_moves) == 1


class TestMoveRequestResult:
    """MoveRequestResult preserves accepted/rejected semantics."""

    def test_accepted(self):
        r = MoveRequestResult(is_accepted=True, reason="ok")
        assert r.is_accepted is True

    def test_rejected(self):
        r = MoveRequestResult(is_accepted=False, reason="illegal_piece_move")
        assert r.is_accepted is False
        assert r.reason == "illegal_piece_move"
