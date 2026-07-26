"""
Tests for the score system.

Verifies that captures update score correctly and that non-capture
events (stops, promotions, friendly collisions) do not affect score.
"""

from game.engine.game_engine import GameEngine
from game.io.piece_token_codec import parse_board
from game.model.constants import MOVE_DURATION_MS


class TestPawnCapture:
    def test_pawn_capture_adds_1(self):
        board = parse_board([
            [".", ".", ".", "."],
            [".", "bP", ".", "."],
            ["wP", ".", ".", "."],
            [".", ".", ".", "."],
        ])
        engine = GameEngine(board)
        # wP captures bP diagonally
        engine.request_move(2, 0, 1, 1)
        engine.handle_wait(MOVE_DURATION_MS + 1)
        assert engine.white_score == 1
        assert engine.black_score == 0


class TestKnightCapture:
    def test_knight_capture_adds_3(self):
        # wR at (0,0) captures bN at (0,3) directly
        board = parse_board([["wR", ".", ".", "bN"]])
        engine = GameEngine(board)
        engine.request_move(0, 0, 0, 3)
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)
        assert engine.white_score == 3


class TestBishopCapture:
    def test_bishop_capture_adds_3(self):
        board = parse_board([["wR", ".", ".", "bB"]])
        engine = GameEngine(board)
        engine.request_move(0, 0, 0, 3)
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)
        assert engine.white_score == 3


class TestRookCapture:
    def test_rook_capture_adds_5(self):
        board = parse_board([["wR", ".", ".", "bR"]])
        engine = GameEngine(board)
        engine.request_move(0, 0, 0, 3)
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)
        assert engine.white_score == 5
        assert engine.black_score == 0


class TestQueenCapture:
    def test_queen_capture_adds_9(self):
        board = parse_board([["wR", ".", ".", "bQ"]])
        engine = GameEngine(board)
        engine.request_move(0, 0, 0, 3)
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)
        assert engine.white_score == 9


class TestKingCapture:
    def test_king_capture_adds_0_and_ends_game(self):
        board = parse_board([["wR", ".", ".", "bK"]])
        engine = GameEngine(board)
        engine.request_move(0, 0, 0, 3)
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)
        assert engine.white_score == 0
        assert engine.game_over is True


class TestMultipleCaptures:
    def test_accumulation(self):
        board = parse_board([
            ["wR", ".", "bP", ".", "bP", ".", ".", "."],
        ])
        engine = GameEngine(board)
        # Capture first pawn at (0,2)
        engine.request_move(0, 0, 0, 2)
        engine.handle_wait(2 * MOVE_DURATION_MS + 1)
        assert engine.white_score == 1

        # Wait for cooldown (2000ms), then capture second pawn at (0,4)
        from game.model.constants import COOLDOWN_DURATION_MS
        engine.handle_wait(COOLDOWN_DURATION_MS + 1)
        engine.request_move(0, 2, 0, 4)
        engine.handle_wait(2 * MOVE_DURATION_MS + 1)
        assert engine.white_score == 2


class TestFriendlyCollisionNoScore:
    def test_friendly_stop_no_score(self):
        board = parse_board([
            ["wR", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", "wR", ".", ".", ".", ".", "."],
        ])
        engine = GameEngine(board)
        engine.request_move(0, 0, 0, 3)
        engine.request_move(1, 2, 0, 2)
        engine.handle_wait(4 * MOVE_DURATION_MS)
        assert engine.white_score == 0
        assert engine.black_score == 0


class TestStoppedMoveNoScore:
    def test_stopped_no_score(self):
        board = parse_board([
            ["wR", ".", ".", "wB", ".", ".", ".", "."],
        ])
        engine = GameEngine(board)
        # wR can't move through wB, so rule engine blocks this
        result = engine.request_move(0, 0, 0, 5)
        # Path blocked by wB at (0,3) → rejected
        assert result.is_accepted is False
        assert engine.white_score == 0


class TestPromotionNoScore:
    def test_promotion_alone_no_score(self):
        board = parse_board([
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wP", ".", ".", ".", ".", ".", ".", "."],
        ])
        engine = GameEngine(board)
        engine.request_move(1, 0, 0, 0)
        engine.handle_wait(MOVE_DURATION_MS + 1)
        assert engine.white_score == 0
        assert engine.black_score == 0


class TestNoCaptureCountedTwice:
    def test_single_capture_single_score(self):
        board = parse_board([["wR", ".", ".", "bR"]])
        engine = GameEngine(board)
        engine.request_move(0, 0, 0, 3)

        # Advance in small increments like the game loop
        for _ in range(300):
            engine.handle_wait(16.67)

        assert engine.white_score == 5  # exactly 5, not 10


class TestScoreAfterGameOver:
    def test_score_remains_after_game_over(self):
        # wR captures bP then bK in a row
        board = parse_board([["wR", ".", "bP", ".", ".", "bK", ".", "."]])
        engine = GameEngine(board)
        # Capture bP at (0,2)
        engine.request_move(0, 0, 0, 2)
        engine.handle_wait(2 * MOVE_DURATION_MS + 1)
        assert engine.white_score == 1

        # Wait cooldown, capture bK at (0,5)
        from game.model.constants import COOLDOWN_DURATION_MS
        engine.handle_wait(COOLDOWN_DURATION_MS + 1)
        engine.request_move(0, 2, 0, 5)
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)
        assert engine.game_over is True
        # Score from pawn still there, king gives 0
        assert engine.white_score == 1


class TestBlackCaptures:
    def test_black_captures_white(self):
        board = parse_board([["bR", ".", ".", "wR"]])
        engine = GameEngine(board)
        engine.request_move(0, 0, 0, 3)
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)
        assert engine.black_score == 5
        assert engine.white_score == 0
