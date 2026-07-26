def is_inside_board(board, row, col):
    """Return True if (row, col) is a valid position on the board."""
    return 0 <= row < len(board) and 0 <= col < len(board[0])
