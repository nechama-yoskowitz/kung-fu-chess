"""
Domain piece helpers — provides a uniform API for querying pieces.

TEMPORARY DUAL-MODE SUPPORT:
During the migration from raw string tokens ("wR", "bK", ".") to domain
Piece objects, these helpers accept BOTH representations. Once all callers
are migrated to use Piece objects, the string-handling branches will be
removed. Do not add new string-based logic elsewhere.

After migration is complete:
- Remove all `isinstance(piece, str)` branches
- Remove EMPTY_CELL import
- Remove string indexing
"""

from game.model.constants import EMPTY_CELL, PIECE_KING, PIECE_PAWN, PIECE_QUEEN
from game.model.piece import Piece, PieceColor, PieceType


# ─── Color constants for comparison (used by callers like rules.py) ────────────
# These map to PieceColor but are kept for backward compat during migration.
_COLOR_WHITE = "w"
_COLOR_BLACK = "b"


def get_color(piece):
    """
    Returns the color of a piece.

    For Piece objects: returns PieceColor enum value.
    For legacy strings: returns 'w' or 'b', or None for empty cell.
    """
    if piece is None:
        return None
    if isinstance(piece, Piece):
        return piece.color
    # --- TEMPORARY: legacy string support ---
    if piece == EMPTY_CELL:
        return None
    return piece[0]


def get_type(piece):
    """
    Returns the type of a piece.

    For Piece objects: returns PieceType enum value.
    For legacy strings: returns 'K', 'Q', etc., or None for empty cell.
    """
    if piece is None:
        return None
    if isinstance(piece, Piece):
        return piece.type
    # --- TEMPORARY: legacy string support ---
    if piece == EMPTY_CELL:
        return None
    return piece[1]


def is_empty(piece):
    """Return True if the cell is empty (None or legacy '.' token)."""
    if piece is None:
        return True
    if isinstance(piece, Piece):
        return False
    # --- TEMPORARY: legacy string support ---
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
    # --- TEMPORARY: legacy string support ---
    return get_type(piece) == PIECE_KING


def is_pawn(piece):
    """Return True if the piece is a pawn."""
    if piece is None:
        return False
    if isinstance(piece, Piece):
        return piece.type == PieceType.PAWN
    # --- TEMPORARY: legacy string support ---
    return get_type(piece) == PIECE_PAWN


def is_queen(piece):
    """Return True if the piece is a queen."""
    if piece is None:
        return False
    if isinstance(piece, Piece):
        return piece.type == PieceType.QUEEN
    # --- TEMPORARY: legacy string support ---
    return get_type(piece) == PIECE_QUEEN


def make_piece(color, piece_type):
    """
    Create a piece from color and type.

    For PieceColor + PieceType: returns a Piece object.
    For legacy string color + string type: returns a legacy string token.
    """
    if isinstance(color, PieceColor) and isinstance(piece_type, PieceType):
        return Piece(color, piece_type)
    # --- TEMPORARY: legacy string support ---
    return color + piece_type
