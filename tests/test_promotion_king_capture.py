"""
Regression tests for pawn capturing king on the promotion row.

Verifies:
- Pawn captures enemy king on promotion row: game ends, no promotion, king capture logged
- Pawn captures non-king on promotion row: promotion still occurs, capture logged
- Pawn reaches promotion row without capturing: normal promotion
"""

from game.engine.game_engine import GameEngine
from game.events import EventBus
from game.events.engine_events import GameEnded, MoveResolved
from game.history.move_history_observer import MoveHistoryObserver
from game.model.constants import MOVE_DURATION_MS
from game.model.piece import BLACK_KING, BLACK_ROOK, WHITE_KING, WHITE_QUEEN, WHITE_PAWN, BLACK_PAWN, PieceColor
from game.io.piece_token_codec import parse_board


class TestPawnCapturesKingOnPromotionRow:
    """Pawn captures enemy king on the promotion row — game ends, no promotion."""

    def test_game_ends_white_wins(self):
        # White pawn at row 1, black king at row 0 col 1 (promotion row for white)
        board = [
            [".", "bK", ".", "."],
            ["wP", ".", ".", "."],
        ]
        engine = GameEngine(board)

        engine.request_move(1, 0, 0, 1)  # wP captures bK diagonally
        engine.handle_wait(MOVE_DURATION_MS + 1)

        assert engine.game_over is True

    def test_winner_is_white(self):
        board = [
            [".", "bK", ".", "."],
            ["wP", ".", ".", "."],
        ]
        engine = GameEngine(board)
        winners = []
        engine.event_bus.subscribe(GameEnded, lambda e: winners.append(e.winner))

        engine.request_move(1, 0, 0, 1)
        engine.handle_wait(MOVE_DURATION_MS + 1)

        assert winners == [PieceColor.WHITE]

    def test_captured_piece_is_king(self):
        board = [
            [".", "bK", ".", "."],
            ["wP", ".", ".", "."],
        ]
        engine = GameEngine(board)
        resolved = []
        engine.event_bus.subscribe(MoveResolved, lambda e: resolved.append(e))

        engine.request_move(1, 0, 0, 1)
        engine.handle_wait(MOVE_DURATION_MS + 1)

        assert len(resolved) >= 1
        capture_event = resolved[0]
        assert capture_event.captured_piece == BLACK_KING

    def test_no_promotion_occurs(self):
        board = [
            [".", "bK", ".", "."],
            ["wP", ".", ".", "."],
        ]
        engine = GameEngine(board)
        resolved = []
        engine.event_bus.subscribe(MoveResolved, lambda e: resolved.append(e))

        engine.request_move(1, 0, 0, 1)
        engine.handle_wait(MOVE_DURATION_MS + 1)

        capture_event = resolved[0]
        assert capture_event.promoted_to is None

    def test_history_mentions_king_capture(self):
        board = [
            [".", "bK", ".", "."],
            ["wP", ".", ".", "."],
        ]
        engine = GameEngine(board)
        history = MoveHistoryObserver(
            event_bus=engine.event_bus,
            clock_provider=lambda: engine.clock,
        )

        engine.request_move(1, 0, 0, 1)
        engine.handle_wait(MOVE_DURATION_MS + 1)

        assert len(history.white_moves) == 1
        desc = history.white_moves[0]["move"]
        assert "King" in desc
        assert "Queen" not in desc

    def test_black_pawn_captures_white_king(self):
        # Black pawn at row 6, white king at row 7 col 1 (promotion row for black)
        board = [
            [".", ".", ".", "."],
            [".", ".", ".", "."],
            [".", ".", ".", "."],
            [".", ".", ".", "."],
            [".", ".", ".", "."],
            [".", ".", ".", "."],
            [".", "bP", ".", "."],
            [".", ".", "wK", "."],
        ]
        engine = GameEngine(board)
        resolved = []
        engine.event_bus.subscribe(MoveResolved, lambda e: resolved.append(e))
        winners = []
        engine.event_bus.subscribe(GameEnded, lambda e: winners.append(e.winner))

        engine.request_move(6, 1, 7, 2)  # bP captures wK diagonally
        engine.handle_wait(MOVE_DURATION_MS + 1)

        assert engine.game_over is True
        assert winners == [PieceColor.BLACK]
        assert resolved[0].captured_piece == WHITE_KING
        assert resolved[0].promoted_to is None


class TestPawnCapturesNonKingOnPromotionRow:
    """Pawn captures non-king on promotion row — promotion still occurs."""

    def test_promotion_with_capture(self):
        board = [
            [".", "bR", ".", "."],
            ["wP", ".", ".", "."],
        ]
        engine = GameEngine(board)
        resolved = []
        engine.event_bus.subscribe(MoveResolved, lambda e: resolved.append(e))

        engine.request_move(1, 0, 0, 1)  # wP captures bR
        engine.handle_wait(MOVE_DURATION_MS + 1)

        event = resolved[0]
        assert event.captured_piece == BLACK_ROOK
        assert event.promoted_to == WHITE_QUEEN
        assert engine.board[0][1] == WHITE_QUEEN

    def test_history_mentions_both_promotion_and_capture(self):
        board = [
            [".", "bR", ".", "."],
            ["wP", ".", ".", "."],
        ]
        engine = GameEngine(board)
        history = MoveHistoryObserver(
            event_bus=engine.event_bus,
            clock_provider=lambda: engine.clock,
        )

        engine.request_move(1, 0, 0, 1)
        engine.handle_wait(MOVE_DURATION_MS + 1)

        desc = history.white_moves[0]["move"]
        assert "Queen" in desc
        assert "Rook" in desc


class TestPawnPromotionWithoutCapture:
    """Pawn reaches promotion row without capturing — normal promotion."""

    def test_normal_promotion(self):
        board = [
            [".", ".", ".", "."],
            ["wP", ".", ".", "."],
        ]
        engine = GameEngine(board)
        resolved = []
        engine.event_bus.subscribe(MoveResolved, lambda e: resolved.append(e))

        engine.request_move(1, 0, 0, 0)  # wP moves straight to row 0
        engine.handle_wait(MOVE_DURATION_MS + 1)

        event = resolved[0]
        assert event.promoted_to == WHITE_QUEEN
        assert event.captured_piece is None
        assert engine.board[0][0] == WHITE_QUEEN

    def test_history_mentions_promotion(self):
        board = [
            [".", ".", ".", "."],
            ["wP", ".", ".", "."],
        ]
        engine = GameEngine(board)
        history = MoveHistoryObserver(
            event_bus=engine.event_bus,
            clock_provider=lambda: engine.clock,
        )

        engine.request_move(1, 0, 0, 0)
        engine.handle_wait(MOVE_DURATION_MS + 1)

        desc = history.white_moves[0]["move"]
        assert "Queen" in desc
        assert "King" not in desc
