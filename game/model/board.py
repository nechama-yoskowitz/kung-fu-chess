from game.model.constants import EMPTY_CELL


def is_inside_board(board, row, col):
    """Return True if (row, col) is a valid position on the board."""
    return 0 <= row < len(board) and 0 <= col < len(board[0])





def move_piece(board, from_row, from_col, to_row, to_col):
    """Move a piece on the board (captures destination if occupied)."""
    board[to_row][to_col] = board[from_row][from_col]
    board[from_row][from_col] = EMPTY_CELL
