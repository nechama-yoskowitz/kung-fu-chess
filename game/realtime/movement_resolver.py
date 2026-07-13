from game.model.board import move_piece
from game.model.constants import (
    EMPTY_CELL,
    PIECE_QUEEN,
)
from game.model.pieces import get_color, get_type, is_king, is_pawn, make_piece
from game.realtime.motion import get_airborne_piece_at
from game.rules.rules import pawn_promotion_row


def expire_jumps(active_jumps, clock):
    """Return only jumps that have not expired yet."""
    return [
        jump
        for jump in active_jumps
        if jump.expires_at >= clock
    ]


def apply_arrived_moves(
    board,
    pending_moves,
    clock,
    active_jumps=None,
):
    """
    Resolve every pending move that reached its arrival time.

    Returns:
        (still_pending, game_over, active_jumps, arrived_cells)

    arrived_cells is a list of (piece, row, col) tuples for pieces
    that successfully landed at their destination.
    """
    if active_jumps is None:
        active_jumps = []

    still_pending = []
    game_over = False
    arrived_cells = []

    for move in pending_moves:
        if move.arrive_at > clock:
            if not game_over:
                still_pending.append(move)
            continue

        if game_over:
            continue

        if board[move.from_row][move.from_col] != move.piece:
            continue

        airborne = get_airborne_piece_at(
            active_jumps,
            move.to_row,
            move.to_col,
        )

        if (
            airborne is not None
            and get_color(airborne.piece) != get_color(move.piece)
        ):
            board[move.from_row][move.from_col] = EMPTY_CELL

            if _is_king(move.piece):
                game_over = True

            continue

        captured_piece = board[move.to_row][move.to_col]

        move_piece(
            board,
            move.from_row,
            move.from_col,
            move.to_row,
            move.to_col,
        )

        _apply_pawn_promotion(board, move)

        # Record successful arrival (use the piece now at destination
        # which may have been promoted).
        landed_piece = board[move.to_row][move.to_col]
        arrived_cells.append((landed_piece, move.to_row, move.to_col))

        if _is_king(captured_piece):
            game_over = True

    return still_pending, game_over, active_jumps, arrived_cells


def _apply_pawn_promotion(board, move):
    """Promote a pawn that reached the final row to a queen."""
    if not is_pawn(move.piece):
        return

    color = get_color(move.piece)

    if move.to_row == pawn_promotion_row(board, color):
        board[move.to_row][move.to_col] = make_piece(color, PIECE_QUEEN)


def _is_king(piece):
    """Return True if the token represents a king."""
    return is_king(piece)