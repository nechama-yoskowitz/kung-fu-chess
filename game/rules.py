from game.constants import (
    EMPTY_CELL,
    PIECE_PAWN,
    PIECE_QUEEN,
    SLIDING_PIECES,
    MOVEMENT_RULES,
    WHITE,
    BLACK,
)
from game.pieces import get_type, get_color


def is_legal_move(piece, from_row, from_col, to_row, to_col):
    """Check if a non-pawn piece move is geometrically legal (ignores board state)."""
    row_diff = abs(to_row - from_row)
    col_diff = abs(to_col - from_col)
    rule = MOVEMENT_RULES.get(get_type(piece))
    if rule is None:
        return False
    return rule(row_diff, col_diff)


def pawn_starting_row(board, color):
    """
    Return the starting row index for a pawn of the given color.
    White pawns start on the last row (len(board) - 1).
    Black pawns start on the first row (0).
    """
    if color == WHITE:
        return len(board) - 1
    return 0


def is_legal_pawn_move(board, piece, from_row, from_col, to_row, to_col):
    """Check if a pawn move is legal given the current board state."""
    row_diff = to_row - from_row
    col_diff = to_col - from_col
    target   = board[to_row][to_col]
    color     = get_color(piece)
    direction = -1 if color == WHITE else 1

    # One square forward — destination must be empty
    if row_diff == direction and col_diff == 0:
        return target == EMPTY_CELL

    # Diagonal capture — destination must have an enemy piece
    if row_diff == direction and abs(col_diff) == 1:
        return target != EMPTY_CELL and target[0] != color

    # Two squares forward — only from starting row, straight, path must be clear
    if row_diff == 2 * direction and col_diff == 0:
        if from_row != pawn_starting_row(board, color):
            return False
        if target != EMPTY_CELL:
            return False
        return is_path_clear(board, from_row, from_col, to_row, to_col)

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


def pawn_promotion_row(board, color):
    """Return the row a pawn must reach to be promoted."""
    if color == WHITE:
        return 0
    return len(board) - 1


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
