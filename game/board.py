from game.constants import EMPTY_CELL, VALID_TOKENS, ERROR_ROW_WIDTH_MISMATCH, ERROR_UNKNOWN_TOKEN


def is_inside_board(board, row, col):
    """Return True if (row, col) is a valid position on the board."""
    return 0 <= row < len(board) and 0 <= col < len(board[0])


def validate_board(board):
    """
    Validate that all rows have equal width and all tokens are known.
    Prints an error and returns False on failure.
    """
    expected_width = None

    for row in board:
        if expected_width is None:
            expected_width = len(row)
        elif len(row) != expected_width:
            print(ERROR_ROW_WIDTH_MISMATCH)
            return False

        for token in row:
            if token not in VALID_TOKENS:
                print(ERROR_UNKNOWN_TOKEN)
                return False

    return True


def print_board(board):
    """Print every row of the board as space-separated tokens."""
    for row in board:
        print(" ".join(row))


def move_piece(board, from_row, from_col, to_row, to_col):
    """Move a piece on the board (captures destination if occupied)."""
    board[to_row][to_col] = board[from_row][from_col]
    board[from_row][from_col] = EMPTY_CELL
