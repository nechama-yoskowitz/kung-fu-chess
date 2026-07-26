from game.model.constants import (
    MOVEMENT_RULES,
    SLIDING_PIECES,
)
from game.model.piece import PieceColor
from game.model.pieces import get_color, get_type, is_empty


def is_legal_move(piece, from_row, from_col, to_row, to_col):
    """
    Check whether a non-pawn piece move is geometrically legal.

    This function ignores the current board state.
    It only checks the movement shape for the piece type.
    """
    row_diff = abs(to_row - from_row)
    col_diff = abs(to_col - from_col)

    rule = MOVEMENT_RULES.get(get_type(piece))

    if rule is None:
        return False

    return rule(row_diff, col_diff)


def pawn_starting_row(board, color):
    """
    Return the starting row index for a pawn of the given color.

    White pawns start one row above the bottom edge.
    Black pawns start one row below the top edge.
    """
    if color == PieceColor.WHITE:
        return len(board) - 2

    return 1


def pawn_promotion_row(board, color):
    """Return the row a pawn must reach in order to be promoted."""
    if color == PieceColor.WHITE:
        return 0

    return len(board) - 1


def is_legal_pawn_move(
    board,
    piece,
    from_row,
    from_col,
    to_row,
    to_col,
):
    """Check whether a pawn move is legal for the current board state."""
    row_diff = to_row - from_row
    col_diff = to_col - from_col

    target = board[to_row][to_col]
    color = get_color(piece)
    direction = -1 if color == PieceColor.WHITE else 1

    # One square forward: the destination must be empty.
    if row_diff == direction and col_diff == 0:
        return is_empty(target)

    # Diagonal capture: the destination must contain an enemy piece.
    if row_diff == direction and abs(col_diff) == 1:
        return not is_empty(target) and get_color(target) != color

    # Two squares forward: only from the starting row,
    # with an empty destination and a clear path.
    if row_diff == 2 * direction and col_diff == 0:
        if from_row != pawn_starting_row(board, color):
            return False

        if not is_empty(target):
            return False

        return is_path_clear(
            board,
            from_row,
            from_col,
            to_row,
            to_col,
        )

    return False


def is_path_clear(
    board,
    from_row,
    from_col,
    to_row,
    to_col,
):
    """
    Return True when no piece blocks the path between source and destination.

    This function is intended for straight and diagonal sliding moves.
    The destination square itself is not checked here.
    """
    row_step = _sign(to_row - from_row)
    col_step = _sign(to_col - from_col)

    current_row = from_row + row_step
    current_col = from_col + col_step

    while (current_row, current_col) != (to_row, to_col):
        if not is_empty(board[current_row][current_col]):
            return False

        current_row += row_step
        current_col += col_step

    return True


def is_sliding_piece(piece):
    """Return True if the piece needs a clear-path check."""
    return get_type(piece) in SLIDING_PIECES


def _sign(value):
    """Return -1, 0, or 1 according to the sign of the value."""
    if value > 0:
        return 1

    if value < 0:
        return -1

    return 0