"""
Tests for the domain Piece type and text token codec.

Verifies:
- Piece is immutable
- Token codec correctly converts between text and domain
- Board does not store raw strings after conversion
- Alternative token formats would only require changing the codec
"""

import dataclasses

import pytest

from game.model.piece import (
    Piece, PieceColor, PieceType,
    WHITE_KING, WHITE_ROOK, BLACK_PAWN, BLACK_KING,
    white, black,
)
from game.io.piece_token_codec import (
    parse_token, format_piece, parse_board, format_board,
    is_valid_token, VALID_TOKENS,
)


class TestPieceType:
    def test_piece_is_immutable(self):
        p = Piece(PieceColor.WHITE, PieceType.ROOK)
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.color = PieceColor.BLACK

    def test_piece_equality(self):
        p1 = Piece(PieceColor.WHITE, PieceType.ROOK)
        p2 = Piece(PieceColor.WHITE, PieceType.ROOK)
        assert p1 == p2

    def test_different_pieces_not_equal(self):
        assert WHITE_KING != BLACK_KING
        assert WHITE_ROOK != WHITE_KING

    def test_is_white(self):
        assert WHITE_ROOK.is_white is True
        assert BLACK_PAWN.is_white is False

    def test_is_black(self):
        assert BLACK_PAWN.is_black is True
        assert WHITE_ROOK.is_black is False

    def test_convenience_constructors(self):
        assert white(PieceType.QUEEN) == Piece(PieceColor.WHITE, PieceType.QUEEN)
        assert black(PieceType.KNIGHT) == Piece(PieceColor.BLACK, PieceType.KNIGHT)


class TestTokenCodecParse:
    def test_parse_empty(self):
        assert parse_token(".") is None

    def test_parse_white_rook(self):
        p = parse_token("wR")
        assert p == Piece(PieceColor.WHITE, PieceType.ROOK)

    def test_parse_black_king(self):
        p = parse_token("bK")
        assert p == Piece(PieceColor.BLACK, PieceType.KING)

    def test_parse_all_valid_tokens(self):
        for token in VALID_TOKENS:
            result = parse_token(token)
            if token == ".":
                assert result is None
            else:
                assert isinstance(result, Piece)

    def test_parse_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_token("xZ")

    def test_parse_unknown_single_char(self):
        with pytest.raises(ValueError):
            parse_token("X")


class TestTokenCodecFormat:
    def test_format_none(self):
        assert format_piece(None) == "."

    def test_format_white_rook(self):
        assert format_piece(WHITE_ROOK) == "wR"

    def test_format_black_king(self):
        assert format_piece(BLACK_KING) == "bK"

    def test_roundtrip(self):
        for token in VALID_TOKENS:
            assert format_piece(parse_token(token)) == token


class TestBoardConversion:
    def test_parse_board(self):
        tokens = [["wR", ".", "bK"]]
        board = parse_board(tokens)
        assert board[0][0] == WHITE_ROOK
        assert board[0][1] is None
        assert board[0][2] == BLACK_KING

    def test_format_board(self):
        board = [[WHITE_ROOK, None, BLACK_KING]]
        tokens = format_board(board)
        assert tokens == [["wR", ".", "bK"]]

    def test_board_does_not_store_raw_strings(self):
        tokens = [["wP", "bQ"]]
        board = parse_board(tokens)
        for cell in board[0]:
            assert not isinstance(cell, str)


class TestValidTokenCheck:
    def test_valid_tokens(self):
        assert is_valid_token("wR") is True
        assert is_valid_token(".") is True
        assert is_valid_token("bK") is True

    def test_invalid_tokens(self):
        assert is_valid_token("xZ") is False
        assert is_valid_token("") is False
        assert is_valid_token("WHITE_ROOK") is False


class TestAlternativeCodecDecoupling:
    """
    Demonstrate that an alternative parser can map different tokens
    to the same internal Piece without changing domain code.
    """

    def test_alternative_token_format(self):
        # An alternative codec that maps "WHITE_ROOK" → same Piece
        alt_map = {
            "WHITE_ROOK": Piece(PieceColor.WHITE, PieceType.ROOK),
            "BLACK_KING": Piece(PieceColor.BLACK, PieceType.KING),
            "EMPTY": None,
        }

        def alt_parse(token: str) -> Piece | None:
            return alt_map[token]

        # Same internal representation regardless of input format
        assert alt_parse("WHITE_ROOK") == parse_token("wR")
        assert alt_parse("BLACK_KING") == parse_token("bK")
        assert alt_parse("EMPTY") == parse_token(".")
