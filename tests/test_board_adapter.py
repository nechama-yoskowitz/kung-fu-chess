"""
Tests for the board adapter at the engine boundary.

Verifies:
- Legacy board converts to domain board
- Domain board converts to legacy board
- Roundtrip preserves contents
- Engine exposes legacy_board for external consumers
- Graphics/network boundaries receive string boards
"""

from game.model.board_adapter import (
    to_domain_board, to_legacy_board, to_domain_piece, to_legacy_piece,
)
from game.model.piece import (
    Piece, PieceColor, PieceType,
    WHITE_ROOK, BLACK_KING, WHITE_PAWN, BLACK_PAWN,
)
from game.engine.game_engine import GameEngine


class TestBoardAdapterConversion:
    def test_legacy_to_domain(self):
        legacy = [["wR", ".", "bK"]]
        domain = to_domain_board(legacy)
        assert domain[0][0] == WHITE_ROOK
        assert domain[0][1] is None
        assert domain[0][2] == BLACK_KING

    def test_domain_to_legacy(self):
        domain = [[WHITE_ROOK, None, BLACK_KING]]
        legacy = to_legacy_board(domain)
        assert legacy == [["wR", ".", "bK"]]

    def test_roundtrip_legacy(self):
        original = [["wR", ".", "bK"], [".", "wP", "."]]
        expected = [["wR", ".", "bK"], [".", "wP", "."]]
        domain = to_domain_board(original)  # in-place conversion
        assert to_legacy_board(domain) == expected

    def test_roundtrip_domain(self):
        original = [[WHITE_ROOK, None, BLACK_KING]]
        assert to_domain_board(to_legacy_board(original)) == original

    def test_already_legacy_passthrough(self):
        legacy = [["wR", "."]]
        result = to_legacy_board(legacy)
        assert result is legacy  # Same object — no unnecessary copy

    def test_already_domain_passthrough(self):
        domain = [[WHITE_ROOK, None]]
        result = to_domain_board(domain)
        assert result is domain


class TestPieceAdapterConversion:
    def test_legacy_to_domain(self):
        assert to_domain_piece("wR") == WHITE_ROOK
        assert to_domain_piece(".") is None

    def test_domain_to_legacy(self):
        assert to_legacy_piece(WHITE_ROOK) == "wR"
        assert to_legacy_piece(None) == "."

    def test_already_piece_passthrough(self):
        p = WHITE_ROOK
        assert to_domain_piece(p) is p

    def test_already_string_passthrough(self):
        s = "bK"
        assert to_legacy_piece(s) is s


class TestEngineLegacyBoard:
    def test_engine_legacy_board_returns_strings(self):
        """Engine.legacy_board provides string format for external consumers."""
        board = [["wR", ".", ".", "bK"]]
        engine = GameEngine(board)
        legacy = engine.legacy_board
        assert all(isinstance(cell, str) for row in legacy for cell in row)
        assert legacy[0][0] == "wR"
        assert legacy[0][1] == "."

    def test_engine_board_is_internal(self):
        """Engine.board is the internal domain representation (Piece|None)."""
        board = [["wR", ".", ".", "bK"]]
        engine = GameEngine(board)
        # After migration, internal board contains Piece objects and None
        assert engine.board is board  # in-place conversion preserves reference
        assert isinstance(engine.board[0][0], Piece)
        assert engine.board[0][1] is None

    def test_legacy_board_matches_board_content(self):
        """legacy_board content matches the internal board in string format."""
        board = [
            ["bR", "bN", "bB", "bQ", "bK", "bB", "bN", "bR"],
            ["bP", "bP", "bP", "bP", "bP", "bP", "bP", "bP"],
            [".", ".", ".", ".", ".", ".", ".", "."],
        ]
        expected_legacy = [
            ["bR", "bN", "bB", "bQ", "bK", "bB", "bN", "bR"],
            ["bP", "bP", "bP", "bP", "bP", "bP", "bP", "bP"],
            [".", ".", ".", ".", ".", ".", ".", "."],
        ]
        engine = GameEngine(board)
        assert engine.legacy_board == expected_legacy
