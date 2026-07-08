from game.constants import CELL_SIZE, EMPTY_CELL, PIECE_PAWN, MOVE_DURATION_MS
from game.pieces import get_type, same_color
from game.board import is_inside_board, print_board
from game.rules import is_legal_move, is_legal_pawn_move, is_path_clear, is_sliding_piece
from game.movement import PendingMove, apply_arrived_moves, is_piece_moving, has_any_pending_move_for_color, is_destination_claimed


def handle_click(board, pending_moves, selected, x, y, clock):
    """
    Process a click at pixel coordinates (x, y).

    Returns (selected, new_pending_move_or_None).
    A PendingMove is returned when a legal move is initiated;
    the board is NOT modified here — movement is deferred.
    """
    row = y // CELL_SIZE
    col = x // CELL_SIZE

    if not is_inside_board(board, row, col):
        return selected, None

    clicked_cell = board[row][col]

    # Nothing selected yet — select a piece (only if it is not already moving)
    if selected is None:
        if clicked_cell != EMPTY_CELL and not is_piece_moving(pending_moves, row, col):
            return (row, col), None
        return None, None

    selected_row, selected_col = selected
    selected_piece = board[selected_row][selected_col]

    # Clicking a friendly piece — switch selection (only if it is not already moving)
    if clicked_cell != EMPTY_CELL and same_color(selected_piece, clicked_cell):
        if is_piece_moving(pending_moves, row, col):
            return selected, None
        return (row, col), None

    # Attempt to move — validate legality
    if get_type(selected_piece) == PIECE_PAWN:
        if not is_legal_pawn_move(board, selected_piece, selected_row, selected_col, row, col):
            return None, None
    else:
        if not is_legal_move(selected_piece, selected_row, selected_col, row, col):
            return None, None
        if is_sliding_piece(selected_piece):
            if not is_path_clear(board, selected_row, selected_col, row, col):
                return None, None

    # Block opposite-color moves while any piece is currently in flight.
    # Two pieces of opposite colors may not move concurrently.
    opposite_color = "b" if selected_piece[0] == "w" else "w"
    if has_any_pending_move_for_color(pending_moves, opposite_color):
        return None, None

    # Block moves to a square already claimed by another pending move.
    if is_destination_claimed(pending_moves, row, col):
        return None, None

    pending = PendingMove(
        piece=selected_piece,
        from_row=selected_row,
        from_col=selected_col,
        to_row=row,
        to_col=col,
        arrive_at=clock + MOVE_DURATION_MS,
    )
    return None, pending


def handle_wait(clock, ms):
    """Advance the game clock by ms milliseconds."""
    return clock + ms


def process_commands(board, commands):
    """Execute a list of commands against the board."""
    selected     = None
    clock        = 0
    pending_moves = []

    for command in commands:
        parts = command.split()

        if command == "print board":
            pending_moves = apply_arrived_moves(board, pending_moves, clock)
            print_board(board)

        elif parts[0] == "click":
            x = int(parts[1])
            y = int(parts[2])
            selected, new_move = handle_click(board, pending_moves, selected, x, y, clock)
            if new_move is not None:
                pending_moves.append(new_move)

        elif parts[0] == "wait":
            ms    = int(parts[1])
            clock = handle_wait(clock, ms)
            pending_moves = apply_arrived_moves(board, pending_moves, clock)
