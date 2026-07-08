from game.constants import (
    EMPTY_CELL,
    PIECE_KING, PIECE_QUEEN, PIECE_ROOK, PIECE_BISHOP, PIECE_KNIGHT, PIECE_PAWN,
    SLIDING_PIECES,
)
from game.pieces import get_type, get_color


def is_legal_move(piece, from_row, from_col, to_row, to_col):
    """Check if a non-pawn piece move is geometrically legal (ignores board state)."""
    row_diff = abs(to_row - from_row)
    col_diff = abs(to_col - from_col)
    piece_type = get_type(piece)

    if piece_type == PIECE_KING:
        return row_diff <= 1 and col_diff <= 1

    if piece_type == PIECE_ROOK:
        return from_row == to_row or from_col == to_col

    if piece_type == PIECE_BISHOP:
        return row_diff == col_diff

    if piece_type == PIECE_QUEEN:
        return (
            from_row == to_row or
            from_col == to_col or
            row_diff == col_diff
        )

    if piece_type == PIECE_KNIGHT:
        return (
            (row_diff == 2 and col_diff == 1) or
            (row_diff == 1 and col_diff == 2)
        )

    return False


def is_legal_pawn_move(board, piece, from_row, from_col, to_row, to_col):
    """Check if a pawn move is legal given the current board state."""
    row_diff = to_row - from_row
    col_diff = to_col - from_col
    target = board[to_row][to_col]
    color = get_color(piece)
    direction = -1 if color == "w" else 1

    # Forward move — must be empty
    if row_diff == direction and col_diff == 0:
        return target == EMPTY_CELL

    # Diagonal capture — must have an enemy piece
    if row_diff == direction and abs(col_diff) == 1:
        return target != EMPTY_CELL and target[0] != color

    return False


def is_path_clear(board, from_row, from_col, to_row, to_col):
    """Check that no piece blocks the straight/diagonal path between two squares."""
    row_step = _sign(to_row - from_row)
    col_step = _sign(to_col - from_col)

    current_row = from_row + row_step
    current_col = from_col + col_step

    while (current_row, current_col) != (to_row, to_col):
        if board[current_row][current_col] != EMPTY_CELL:
            return False
        current_row += row_step
        current_col += col_step

    return True


def is_sliding_piece(piece):
    """Return True if the piece slides (Q, R, B) and needs path-clear check."""
    return get_type(piece) in SLIDING_PIECES


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sign(value):
    """Return -1, 0, or 1 depending on the sign of value."""
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0
