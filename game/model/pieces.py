from game.model.constants import EMPTY_CELL


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


def same_color(piece1, piece2):
    """Check if two pieces are the same color."""
    return piece1 != EMPTY_CELL and piece2 != EMPTY_CELL and piece1[0] == piece2[0]
