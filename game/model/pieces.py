"""
Domain piece helpers — provides a uniform API for querying pieces.

These helpers accept both Piece objects and legacy string tokens because
the client-side controller operates on string boards received from the
network protocol. Once the client converts to domain boards, the string
branches can be removed.
"""

from game.model.constants import EMPTY_CELL, PIECE_KING, PIECE_PAWN, PIECE_QUEEN
from game.model.piece import Piece, PieceColor, PieceType


def get_color(piece):
    """
    Returns the color of a piece.

    For Piece objects: returns PieceColor enum value.
    For legacy strings (client boundary): returns 'w' or 'b', or None for empty.
    """
    if piece is None:
        return None
    if isinstance(piece, Piece):
        return piece.color
    # Client boundary: legacy string support
    if piece == EMPTY_CELL:
        return None
    return piece[0]


def get_type(piece):
    """
    Returns the type of a piece.

    For Piece objects: returns PieceType enum value.
    For legacy strings (client boundary): returns 'K', 'Q', etc.
    """
    if piece is None:
        return None
    if isinstance(piece, Piece):
        return piece.type
    # Client boundary: legacy string support
    if piece == EMPTY_CELL:
        return None
    return piece[1]


def is_empty(piece):
    """Return True if the cell is empty (None or legacy '.' token)."""
    if piece is None:
        return True
    if isinstance(piece, Piece):
        return False
    # Client boundary: legacy string support
    return piece == EMPTY_CELL


def same_color(piece1, piece2):
    """Check if two pieces are the same color. Empty cells are never same-color."""
    if is_empty(piece1) or is_empty(piece2):
        return False
    return get_color(piece1) == get_color(piece2)


def is_king(piece):
    """Return True if the piece is a king."""
    if piece is None:
        return False
    if isinstance(piece, Piece):
        return piece.type == PieceType.KING
    # Client boundary: legacy string support
    return get_type(piece) == PIECE_KING


def is_pawn(piece):
    """Return True if the piece is a pawn."""
    if piece is None:
        return False
    if isinstance(piece, Piece):
        return piece.type == PieceType.PAWN
    # Client boundary: legacy string support
    return get_type(piece) == PIECE_PAWN


def is_queen(piece):
    """Return True if the piece is a queen."""
    if piece is None:
        return False
    if isinstance(piece, Piece):
        return piece.type == PieceType.QUEEN
    # Client boundary: legacy string support
    return get_type(piece) == PIECE_QUEEN


def make_piece(color, piece_type):
    """Create a Piece from PieceColor and PieceType."""
    if isinstance(color, PieceColor) and isinstance(piece_type, PieceType):
        return Piece(color, piece_type)
    # Client boundary: legacy string support
    return color + piece_type
