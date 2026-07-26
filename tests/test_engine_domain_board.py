"""
Focused tests proving GameEngine stores Piece|None internally.

These tests verify the first vertical migration slice:
- GameEngine accepts a legacy string board
- GameEngine.board contains Piece objects and None after construction
- GameEngine.legacy_board returns the original string representation
- A normal move still works on the domain board
- Capture, promotion, and king capture still work
"""

from game.engine.game_engine import GameEngine
from game.model.piece import (
    Piece, PieceColor, PieceType,
    WHITE_ROOK, WHITE_PAWN, WHITE_KING, WHITE_QUEEN,
    BLACK_ROOK, BLACK_PAWN, BLACK_KING, BLACK_QUEEN, BLACK_KNIGHT,
)


def _make_legacy_board(rows):
    """Helper: build a legacy string board from space-separated row strings."""
    return [row.split() for row in rows]


class TestEngineAcceptsLegacyBoard:
    """GameEngine.__init__ accepts legacy string boards and converts them."""

    def test_accepts_legacy_string_board(self):
        board = _make_legacy_board([
            "bR .  .  .  bK .  .  bR",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            "wR .  .  .  wK .  .  wR",
        ])
        engine = GameEngine(board)
        # Should not raise — engine accepts legacy boards
        assert engine.board is not None

    def test_board_contains_piece_objects_and_none(self):
        board = _make_legacy_board([
            "bR .  .  .  bK .  .  bR",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            "wR .  .  .  wK .  .  wR",
        ])
        engine = GameEngine(board)

        # Corner should be a Piece
        assert isinstance(engine.board[0][0], Piece)
        assert engine.board[0][0] == BLACK_ROOK

        # Empty cell should be None, not "."
        assert engine.board[1][0] is None

        # White king
        assert engine.board[7][4] == WHITE_KING

        # No strings anywhere in the board
        for row in engine.board:
            for cell in row:
                assert not isinstance(cell, str), f"Found string '{cell}' in engine.board"

    def test_also_accepts_domain_board_directly(self):
        board = [
            [BLACK_ROOK, None, None, None, BLACK_KING, None, None, BLACK_ROOK],
            [None] * 8,
            [None] * 8,
            [None] * 8,
            [None] * 8,
            [None] * 8,
            [None] * 8,
            [WHITE_ROOK, None, None, None, WHITE_KING, None, None, WHITE_ROOK],
        ]
        engine = GameEngine(board)
        assert engine.board[0][0] == BLACK_ROOK
        assert engine.board[3][3] is None


class TestLegacyBoardProperty:
    """GameEngine.legacy_board returns the original string representation."""

    def test_legacy_board_returns_strings(self):
        board = _make_legacy_board([
            "bR .  .  .  bK .  .  bR",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            "wR .  .  .  wK .  .  wR",
        ])
        engine = GameEngine(board)
        legacy = engine.legacy_board

        assert legacy[0][0] == "bR"
        assert legacy[0][1] == "."
        assert legacy[7][4] == "wK"

        # All cells should be strings
        for row in legacy:
            for cell in row:
                assert isinstance(cell, str)


class TestNormalMoveOnDomainBoard:
    """A normal move still works on the domain board."""

    def test_rook_move_accepted(self):
        board = _make_legacy_board([
            ".  .  .  .  bK .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            "wR .  .  .  wK .  .  .",
        ])
        engine = GameEngine(board)
        result = engine.request_move(7, 0, 7, 3)
        assert result.is_accepted
        assert result.reason == "ok"

    def test_rook_move_updates_board_after_arrival(self):
        board = _make_legacy_board([
            ".  .  .  .  bK .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            "wR .  .  .  wK .  .  .",
        ])
        engine = GameEngine(board)
        engine.request_move(7, 0, 7, 3)
        # Advance enough time for the move to arrive (distance 3 * 1000ms)
        engine.handle_wait(3000)

        # Source should be None
        assert engine.board[7][0] is None
        # Destination should be the piece
        assert engine.board[7][3] == WHITE_ROOK


class TestCaptureOnDomainBoard:
    """Capture still works on the domain board."""

    def test_capture_removes_enemy_piece(self):
        board = _make_legacy_board([
            ".  .  .  .  bK .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  bR .  .  .  .",
            "wR .  .  .  wK .  .  .",
        ])
        engine = GameEngine(board)
        # White rook at (7,0) captures black rook at (6,3) — not legal for rook
        # (can't move diagonally). Instead: move rook straight up to (6,0), then right to (6,3).
        # Step 1: move up to (6,0) — distance 1
        result = engine.request_move(7, 0, 6, 0)
        assert result.is_accepted
        engine.handle_wait(1000)  # arrive
        engine.handle_wait(2000)  # cooldown

        # Step 2: move right to capture black rook at (6,3) — distance 3
        result = engine.request_move(6, 0, 6, 3)
        assert result.is_accepted
        engine.handle_wait(3000)  # arrive

        # The white rook should be at (6,3) after capturing
        assert engine.board[6][3] == WHITE_ROOK
        # Source should be empty
        assert engine.board[6][0] is None


class TestPromotionOnDomainBoard:
    """Promotion still works on the domain board."""

    def test_pawn_promotes_to_queen(self):
        board = _make_legacy_board([
            ".  .  .  .  bK .  .  .",
            "wP .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  wK .  .  .",
        ])
        engine = GameEngine(board)
        result = engine.request_move(1, 0, 0, 0)
        assert result.is_accepted
        # Advance time for arrival (distance 1)
        engine.handle_wait(1000)

        # Pawn should have promoted to queen
        promoted = engine.board[0][0]
        assert isinstance(promoted, Piece)
        assert promoted.type == PieceType.QUEEN
        assert promoted.color == PieceColor.WHITE


class TestKingCaptureOnDomainBoard:
    """King capture ends the game on the domain board."""

    def test_king_capture_triggers_game_over(self):
        board = _make_legacy_board([
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  .  .  .  .",
            ".  .  .  .  bK .  .  .",
            "wR .  .  .  wK .  .  .",
        ])
        engine = GameEngine(board)
        # White rook captures black king
        result = engine.request_move(7, 0, 6, 0)
        assert result.is_accepted

        # Move rook up one row — but first need it to arrive and cooldown
        engine.handle_wait(1000)  # arrive at (6,0)
        engine.handle_wait(2000)  # cooldown expires

        # Now move to capture king at (6,4)
        result = engine.request_move(6, 0, 6, 4)
        assert result.is_accepted
        engine.handle_wait(4000)  # distance 4

        assert engine.game_over is True
