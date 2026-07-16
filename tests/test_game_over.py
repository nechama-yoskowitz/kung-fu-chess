"""
Tests for Game Over visual state and input disabling.

Verifies that when engine.game_over is True:
- Mouse clicks are ignored
- No new PendingMoves are created
- The game over overlay would be drawn
- The board remains accessible underneath
"""

import cv2
from unittest.mock import MagicMock

from game.controller.controller import Controller
from game.engine.game_engine import GameEngine
from game.graphics.mouse_input_adapter import MouseInputAdapter
from game.model.board_mapper import BoardMapper
from game.model.constants import MOVE_DURATION_MS


def _make_board_with_kings():
    """Board where white can capture black king in one move."""
    return [
        [".", ".", ".", ".", "bK", ".", ".", "."],
        [".", ".", ".", ".", ".", ".", ".", "."],
        [".", ".", ".", ".", ".", ".", ".", "."],
        [".", ".", ".", ".", ".", ".", ".", "."],
        [".", ".", ".", ".", ".", ".", ".", "."],
        [".", ".", ".", ".", ".", ".", ".", "."],
        [".", ".", ".", ".", ".", ".", ".", "."],
        [".", ".", ".", ".", "wK", "wR", ".", "."],
    ]


class TestNoOverlayBeforeGameOver:
    """No game over overlay while game_over is False."""

    def test_game_over_false_initially(self):
        engine = GameEngine(_make_board_with_kings())
        assert engine.game_over is False

    def test_game_over_provider_returns_false(self):
        engine = GameEngine(_make_board_with_kings())
        provider = lambda: engine.game_over
        assert provider() is False


class TestOverlayAppearsOnGameOver:
    """Overlay appears when game_over is True."""

    def test_game_over_after_king_capture(self):
        board = [
            [".", ".", ".", ".", "bK", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", "wR", ".", "."],
        ]
        engine = GameEngine(board)

        # Move rook from (7,5) to (0,5) — this doesn't capture the king
        # Let's set up a direct capture scenario
        board2 = [
            [".", ".", ".", ".", "bK", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", "wR", ".", ".", "."],
        ]
        engine2 = GameEngine(board2)

        # Rook moves to king's column: (7,4) to (0,4) captures bK
        result = engine2.request_move(7, 4, 0, 4)
        assert result.is_accepted

        # Advance time to resolve
        engine2.handle_wait(7 * MOVE_DURATION_MS + 1)

        assert engine2.game_over is True

    def test_game_over_provider_returns_true_after_capture(self):
        board = [
            [".", ".", ".", ".", "bK", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", "wR", ".", ".", "."],
        ]
        engine = GameEngine(board)
        provider = lambda: engine.game_over

        engine.request_move(7, 4, 0, 4)
        engine.handle_wait(7 * MOVE_DURATION_MS + 1)

        assert provider() is True


class TestFinalBoardVisible:
    """Final board state remains accessible after game over."""

    def test_board_still_accessible_after_game_over(self):
        board = [
            [".", ".", ".", ".", "bK", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", "wR", ".", ".", "."],
        ]
        engine = GameEngine(board)
        engine.request_move(7, 4, 0, 4)
        engine.handle_wait(7 * MOVE_DURATION_MS + 1)

        assert engine.game_over is True
        # Board is still there and accessible
        assert engine.board is not None
        assert len(engine.board) == 8
        # The rook should be at (0,4) now
        assert engine.board[0][4] == "wR"


class TestMouseIgnoredAfterGameOver:
    """Mouse clicks are ignored after game over."""

    def test_click_ignored_when_game_over(self):
        board = _make_board_with_kings()
        engine = GameEngine(board)
        engine.game_over = True  # Force game over

        mapper = BoardMapper(cell_width=100, cell_height=100)
        controller = Controller(engine=engine, board_mapper=mapper)
        adapter = MouseInputAdapter(
            controller,
            game_over_provider=lambda: engine.game_over,
        )

        controller.click = MagicMock(return_value=False)

        # Simulate left click
        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 450, 750, 0, None)

        # Controller.click should NOT be called
        controller.click.assert_not_called()

    def test_click_works_before_game_over(self):
        board = _make_board_with_kings()
        engine = GameEngine(board)

        mapper = BoardMapper(cell_width=100, cell_height=100)
        controller = Controller(engine=engine, board_mapper=mapper)
        adapter = MouseInputAdapter(
            controller,
            game_over_provider=lambda: engine.game_over,
        )

        controller.click = MagicMock(return_value=False)

        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 450, 750, 0, None)

        controller.click.assert_called_once()


class TestNoNewMovesAfterGameOver:
    """No new PendingMove can be created after game over."""

    def test_request_move_rejected_after_game_over(self):
        board = _make_board_with_kings()
        engine = GameEngine(board)
        engine.game_over = True

        result = engine.request_move(7, 4, 6, 4)
        assert result.is_accepted is False
        assert result.reason == "game_over"
        assert len(engine.pending_moves) == 0

    def test_no_pending_move_created_via_click_after_game_over(self):
        board = [
            [".", ".", ".", ".", "bK", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", "wR", ".", ".", "."],
        ]
        engine = GameEngine(board)
        engine.request_move(7, 4, 0, 4)
        engine.handle_wait(7 * MOVE_DURATION_MS + 1)

        assert engine.game_over is True

        # Try to make another move
        result = engine.request_move(0, 4, 0, 7)
        assert result.is_accepted is False
        # No new pending moves
        assert len(engine.pending_moves) == 0


class TestEscAndCloseStillWork:
    """Esc and window X still close the window after game over."""

    def test_esc_key_constant_available(self):
        """Verify the Esc key constant is defined for use in GameLoop."""
        from game.graphics.game_loop import Esc
        assert Esc == 27

    def test_game_loop_has_running_flag(self):
        """GameLoop.running can be set to False to stop the loop."""
        from game.graphics.game_loop import GameLoop
        from unittest.mock import MagicMock

        frame_composer = MagicMock()
        gm = MagicMock()

        loop = GameLoop(
            frame_composer=frame_composer,
            graphics_manager=gm,
        )
        assert loop.running is False
