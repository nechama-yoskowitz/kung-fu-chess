from game.constants import CELL_SIZE, EMPTY_CELL, PIECE_PAWN, PIECE_KNIGHT
from game.pieces import get_type, same_color
from game.board import is_inside_board, print_board, move_piece
from game.rules import is_legal_move, is_legal_pawn_move, is_path_clear, is_sliding_piece


def handle_click(board, selected, x, y):
    """
    Process a click at pixel coordinates (x, y).
    Returns the new selected cell (row, col) or None.
    """
    row = y // CELL_SIZE
    col = x // CELL_SIZE

    if not is_inside_board(board, row, col):
        return selected

    clicked_cell = board[row][col]

    # Nothing selected yet — select a piece
    if selected is None:
        if clicked_cell != EMPTY_CELL:
            return (row, col)
        return None

    selected_row, selected_col = selected
    selected_piece = board[selected_row][selected_col]

    # Clicking a friendly piece — switch selection
    if clicked_cell != EMPTY_CELL and same_color(selected_piece, clicked_cell):
        return (row, col)

    # Attempt to move the selected piece
    if get_type(selected_piece) == PIECE_PAWN:
        if not is_legal_pawn_move(board, selected_piece, selected_row, selected_col, row, col):
            return None
        move_piece(board, selected_row, selected_col, row, col)
        return None

    if not is_legal_move(selected_piece, selected_row, selected_col, row, col):
        return None

    if is_sliding_piece(selected_piece):
        if not is_path_clear(board, selected_row, selected_col, row, col):
            return None

    move_piece(board, selected_row, selected_col, row, col)
    return None


def handle_wait(clock, ms):
    """Advance the game clock by ms milliseconds."""
    return clock + ms


def process_commands(board, commands):
    """Execute a list of commands against the board."""
    selected = None
    clock = 0

    for command in commands:
        parts = command.split()

        if command == "print board":
            print_board(board)

        elif parts[0] == "click":
            x = int(parts[1])
            y = int(parts[2])
            selected = handle_click(board, selected, x, y)

        elif parts[0] == "wait":
            ms = int(parts[1])
            clock = handle_wait(clock, ms)
