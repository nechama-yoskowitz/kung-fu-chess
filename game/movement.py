from collections import namedtuple

from game.board import move_piece


# Represents a move that has been committed but has not yet arrived.
#
# Fields:
#   piece      — the piece string (e.g. "wR")
#   from_row   — origin row
#   from_col   — origin column
#   to_row     — destination row
#   to_col     — destination column
#   arrive_at  — clock value (ms) at which the piece lands
PendingMove = namedtuple(
    "PendingMove",
    ["piece", "from_row", "from_col", "to_row", "to_col", "arrive_at"],
)


def apply_arrived_moves(board, pending_moves, clock):
    """
    Land every pending move whose arrive_at <= clock.

    A move is cancelled if the piece is no longer at its origin square
    (another move already displaced it — first mover wins).

    Modifies the board in place and returns a new list containing
    only the moves that have not yet arrived.
    """
    still_pending = []

    for move in pending_moves:
        if move.arrive_at <= clock:
            # Only execute if the piece is still at its origin.
            if board[move.from_row][move.from_col] == move.piece:
                move_piece(board, move.from_row, move.from_col, move.to_row, move.to_col)
            # else: piece was already displaced — move is silently cancelled.
        else:
            still_pending.append(move)

    return still_pending


def is_piece_moving(pending_moves, row, col):
    """Return True if the piece at (row, col) has a pending move in flight."""
    return any(
        move.from_row == row and move.from_col == col
        for move in pending_moves
    )


def has_any_pending_move_for_color(pending_moves, color):
    """Return True if any in-flight move belongs to the given color ('w' or 'b')."""
    return any(move.piece[0] == color for move in pending_moves)


def is_destination_claimed(pending_moves, row, col):
    """Return True if another pending move is already heading to (row, col)."""
    return any(
        move.to_row == row and move.to_col == col
        for move in pending_moves
    )
