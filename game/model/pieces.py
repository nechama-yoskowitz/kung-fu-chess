from game.model.constants import EMPTY_CELL, PIECE_KING, PIECE_PAWN, PIECE_QUEEN


def get_color(piece):
    """Returns the color ('w' or 'b') of a piece, or None for empty cell."""
    if piece == EMPTY_CELL:
        return None
    return piece[0]


def get_type(piece):
    """Returns the type ('K', 'Q', etc.) of a piece, or None for empty cell."""
    if piece == EMPTY_CELL:
        return None
    return piece[1]


def is_empty(piece):
    """Return True if the cell is empty."""
    return piece == EMPTY_CELL


def same_color(piece1, piece2):
    """Check if two pieces are the same color."""
    return piece1 != EMPTY_CELL and piece2 != EMPTY_CELL and piece1[0] == piece2[0]


def is_king(piece):
    """Return True if the piece is a king."""
    return get_type(piece) == PIECE_KING


def is_pawn(piece):
    """Return True if the piece is a pawn."""
    return get_type(piece) == PIECE_PAWN


def is_queen(piece):
    """Return True if the piece is a queen."""
    return get_type(piece) == PIECE_QUEEN


def make_piece(color, piece_type):
    """Create a piece token from color and type."""
    return color + piece_type
