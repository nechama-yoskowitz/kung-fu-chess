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

    Modifies the board in place and returns a new list containing
    only the moves that have not yet arrived.
    """
    still_pending = []

    for move in pending_moves:
        if move.arrive_at < clock:
            move_piece(board, move.from_row, move.from_col, move.to_row, move.to_col)
        else:
            still_pending.append(move)

    return still_pending
