"""
Tests for the dual-mode pieces.py helpers during migration.

Verifies that each helper works correctly with both:
- Legacy string tokens ("wR", "bK", ".")
- New domain Piece objects (Piece, None)

These tests will be simplified once the migration is complete and
string support is removed.
"""

from game.model.piece import Piece, PieceColor, PieceType, WHITE_ROOK, BLACK_KING, WHITE_PAWN, BLACK_PAWN
from game.model.pieces import (
    get_color, get_type, is_empty, same_color, is_king, is_pawn, is_queen, make_piece,
)


class TestGetColorDualMode:
    # --- New Piece objects ---
    def test_piece_white(self):
        assert get_color(WHITE_ROOK) == PieceColor.WHITE

    def test_piece_black(self):
        assert get_color(BLACK_KING) == PieceColor.BLACK

    def test_piece_none(self):
        assert get_color(None) is None

    # --- Legacy strings ---
    def test_string_white(self):
        assert get_color("wR") == "w"

    def test_string_black(self):
        assert get_color("bK") == "b"

    def test_string_empty(self):
        assert get_color(".") is None


class TestGetTypeDualMode:
    # --- New Piece objects ---
    def test_piece_king(self):
        assert get_type(BLACK_KING) == PieceType.KING

    def test_piece_pawn(self):
        assert get_type(WHITE_PAWN) == PieceType.PAWN

    def test_piece_none(self):
        assert get_type(None) is None

    # --- Legacy strings ---
    def test_string_king(self):
        assert get_type("bK") == "K"

    def test_string_pawn(self):
        assert get_type("wP") == "P"

    def test_string_empty(self):
        assert get_type(".") is None


class TestIsEmptyDualMode:
    def test_none_is_empty(self):
        assert is_empty(None) is True

    def test_piece_not_empty(self):
        assert is_empty(WHITE_ROOK) is False

    def test_string_dot_is_empty(self):
        assert is_empty(".") is True

    def test_string_piece_not_empty(self):
        assert is_empty("wR") is False


class TestSameColorDualMode:
    # --- Piece objects ---
    def test_pieces_same_color(self):
        assert same_color(WHITE_ROOK, WHITE_PAWN) is True

    def test_pieces_different_color(self):
        assert same_color(WHITE_ROOK, BLACK_KING) is False

    def test_piece_vs_none(self):
        assert same_color(WHITE_ROOK, None) is False

    # --- Legacy strings ---
    def test_strings_same_color(self):
        assert same_color("wR", "wP") is True

    def test_strings_different_color(self):
        assert same_color("wR", "bK") is False

    def test_string_vs_empty(self):
        assert same_color("wR", ".") is False


class TestIsKingDualMode:
    def test_piece_king(self):
        assert is_king(BLACK_KING) is True

    def test_piece_not_king(self):
        assert is_king(WHITE_ROOK) is False

    def test_none(self):
        assert is_king(None) is False

    def test_string_king(self):
        assert is_king("wK") is True

    def test_string_not_king(self):
        assert is_king("wR") is False


class TestIsPawnDualMode:
    def test_piece_pawn(self):
        assert is_pawn(WHITE_PAWN) is True

    def test_piece_not_pawn(self):
        assert is_pawn(WHITE_ROOK) is False

    def test_string_pawn(self):
        assert is_pawn("bP") is True


class TestIsQueenDualMode:
    def test_piece_queen(self):
        from game.model.piece import WHITE_QUEEN
        assert is_queen(WHITE_QUEEN) is True

    def test_piece_not_queen(self):
        assert is_queen(WHITE_ROOK) is False

    def test_string_queen(self):
        assert is_queen("wQ") is True


class TestMakePieceDualMode:
    # --- New domain types ---
    def test_make_piece_domain(self):
        p = make_piece(PieceColor.WHITE, PieceType.QUEEN)
        assert isinstance(p, Piece)
        assert p.color == PieceColor.WHITE
        assert p.type == PieceType.QUEEN

    # --- Legacy strings ---
    def test_make_piece_legacy(self):
        p = make_piece("w", "Q")
        assert p == "wQ"
        assert isinstance(p, str)
