"""
Core domain types for chess pieces.

These types form the internal representation of pieces on the board.
They must NOT depend on external input formats, graphical asset names,
or network protocol strings.
"""

from dataclasses import dataclass
from enum import Enum


class PieceColor(Enum):
    """The color/side of a chess piece."""
    WHITE = "white"
    BLACK = "black"

    def __eq__(self, other):
        if isinstance(other, PieceColor):
            return self.value == other.value
        # --- TEMPORARY: allow comparison with legacy "w"/"b" strings during migration ---
        if isinstance(other, str):
            if other == "w":
                return self is PieceColor.WHITE
            if other == "b":
                return self is PieceColor.BLACK
        return NotImplemented

    def __hash__(self):
        return hash(self.value)


class PieceType(Enum):
    """The type of a chess piece."""
    KING = "king"
    QUEEN = "queen"
    ROOK = "rook"
    BISHOP = "bishop"
    KNIGHT = "knight"
    PAWN = "pawn"


@dataclass(frozen=True, eq=False)
class Piece:
    """
    Immutable domain representation of a chess piece.

    A board cell contains either a Piece or None (empty).
    """
    color: PieceColor
    type: PieceType

    def __eq__(self, other):
        if isinstance(other, Piece):
            return self.color == other.color and self.type == other.type
        # --- TEMPORARY: allow comparison with legacy string tokens during migration ---
        if isinstance(other, str) and len(other) == 2:
            from game.io.piece_token_codec import _COLOR_MAP, _TYPE_MAP
            expected_color = _COLOR_MAP.get(other[0])
            expected_type = _TYPE_MAP.get(other[1])
            if expected_color is not None and expected_type is not None:
                return self.color == expected_color and self.type == expected_type
        return NotImplemented

    def __hash__(self):
        return hash((self.color, self.type))

    @property
    def is_white(self) -> bool:
        return self.color == PieceColor.WHITE

    @property
    def is_black(self) -> bool:
        return self.color == PieceColor.BLACK


# ─── Convenience constructors ─────────────────────────────────────────────────

def white(piece_type: PieceType) -> Piece:
    return Piece(PieceColor.WHITE, piece_type)

def black(piece_type: PieceType) -> Piece:
    return Piece(PieceColor.BLACK, piece_type)


# ─── Pre-built constants for common usage ─────────────────────────────────────

WHITE_KING   = white(PieceType.KING)
WHITE_QUEEN  = white(PieceType.QUEEN)
WHITE_ROOK   = white(PieceType.ROOK)
WHITE_BISHOP = white(PieceType.BISHOP)
WHITE_KNIGHT = white(PieceType.KNIGHT)
WHITE_PAWN   = white(PieceType.PAWN)

BLACK_KING   = black(PieceType.KING)
BLACK_QUEEN  = black(PieceType.QUEEN)
BLACK_ROOK   = black(PieceType.ROOK)
BLACK_BISHOP = black(PieceType.BISHOP)
BLACK_KNIGHT = black(PieceType.KNIGHT)
BLACK_PAWN   = black(PieceType.PAWN)
