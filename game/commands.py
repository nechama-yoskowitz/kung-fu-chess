from game.constants import CELL_SIZE, EMPTY_CELL, PIECE_PAWN, MOVE_DURATION_MS, JUMP_DURATION_MS
from game.pieces import get_type, same_color
from game.board import is_inside_board, print_board
from game.rules import is_legal_move, is_legal_pawn_move, is_path_clear, is_sliding_piece
from game.movement import (
    PendingMove, ActiveJump,
    apply_arrived_moves, expire_jumps,
    is_piece_moving, is_destination_claimed,
)


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


def handle_jump(board, pending_moves, active_jumps, x, y, clock):
    """
    Process a jump command at pixel coordinates (x, y).

    Returns a new ActiveJump or None if the jump is invalid.
    A jump is invalid if:
      - the cell is empty,
      - the piece is already moving,
      - the piece is already airborne.
    """
    row = y // CELL_SIZE
    col = x // CELL_SIZE

    if not is_inside_board(board, row, col):
        return None

    cell = board[row][col]

    # Cannot jump empty cell
    if cell == EMPTY_CELL:
        return None

    # Cannot jump a piece that is already moving
    if is_piece_moving(pending_moves, row, col):
        return None

    # Cannot jump if already airborne
    for j in active_jumps:
        if j.row == row and j.col == col:
            return None

    return ActiveJump(
        piece=cell,
        row=row,
        col=col,
        expires_at=clock + JUMP_DURATION_MS,
    )


def handle_wait(clock, ms):
    """Advance the game clock by ms milliseconds."""
    return clock + ms


def process_commands(board, commands):
    """Execute a list of commands against the board."""
    selected      = None
    clock         = 0
    pending_moves = []
    active_jumps  = []
    game_over     = False

    for command in commands:
        parts = command.split()

        if command == "print board":
            if not game_over:
                active_jumps = expire_jumps(active_jumps, clock)
                pending_moves, game_over, active_jumps = apply_arrived_moves(
                    board, pending_moves, clock, active_jumps
                )
                if game_over:
                    pending_moves = []
                    active_jumps  = []
            print_board(board)

        elif parts[0] == "click":
            if game_over:
                continue
            x = int(parts[1])
            y = int(parts[2])
            selected, new_move = handle_click(board, pending_moves, selected, x, y, clock)
            if new_move is not None:
                pending_moves.append(new_move)

        elif parts[0] == "jump":
            if game_over:
                continue
            x = int(parts[1])
            y = int(parts[2])
            new_jump = handle_jump(board, pending_moves, active_jumps, x, y, clock)
            if new_jump is not None:
                active_jumps.append(new_jump)

        elif parts[0] == "wait":
            ms    = int(parts[1])
            clock = handle_wait(clock, ms)
            if not game_over:
                active_jumps = expire_jumps(active_jumps, clock)
                pending_moves, game_over, active_jumps = apply_arrived_moves(
                    board, pending_moves, clock, active_jumps
                )
                if game_over:
                    pending_moves = []
                    active_jumps  = []
