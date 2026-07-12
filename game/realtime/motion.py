from dataclasses import dataclass


@dataclass(frozen=True)
class PendingMove:
    """A move that started but has not reached its destination yet."""

    piece: str
    from_row: int
    from_col: int
    to_row: int
    to_col: int
    arrive_at: int


@dataclass(frozen=True)
class ActiveJump:
    """A piece that is currently airborne."""

    piece: str
    row: int
    col: int
    expires_at: int


def is_piece_moving(pending_moves, row, col):
    """Return True if the piece at the cell currently has a pending move."""
    return any(
        move.from_row == row and move.from_col == col
        for move in pending_moves
    )


def is_destination_claimed(pending_moves, row, col):
    """Return True if a pending move is already heading to the cell."""
    return any(
        move.to_row == row and move.to_col == col
        for move in pending_moves
    )


def get_airborne_piece_at(active_jumps, row, col):
    """Return the airborne piece at the cell, or None."""
    for jump in active_jumps:
        if jump.row == row and jump.col == col:
            return jump

    return None