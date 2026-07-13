from dataclasses import dataclass

from game.model.pieces import get_type
from game.model.constants import PIECE_KNIGHT


@dataclass(frozen=True)
class PendingMove:
    """A move that started but has not reached its destination yet."""

    piece: str
    from_row: int
    from_col: int
    to_row: int
    to_col: int
    started_at: int
    arrive_at: int
    sequence_id: int


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


@dataclass(frozen=True)
class ActiveCooldown:
    """A piece that is resting after arriving at its destination."""

    piece: str
    row: int
    col: int
    available_at: int


def is_piece_resting(active_cooldowns, row, col, board):
    """
    Return True if a resting piece occupies the given cell.

    Checks that the piece token still matches the board to avoid
    'orphaned' cooldowns after a capture.
    """
    for cd in active_cooldowns:
        if cd.row == row and cd.col == col:
            if board[row][col] == cd.piece:
                return True
    return False


def _sign(value):
    """Return -1, 0, or 1 according to the sign of value."""
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def compute_path(piece, from_row, from_col, to_row, to_col):
    """
    Compute the list of cells a piece traverses from source to destination.

    Returns a list of (row, col) tuples:
    - Exclusive of the source cell.
    - Inclusive of the destination cell.

    For knights: the path is just [destination] (no intermediate cells).
    For sliding pieces (rook, bishop, queen): every cell along the direction.
    For king/pawn (1-step): just [destination].
    For pawn (2-step): [intermediate, destination].
    """
    if get_type(piece) == PIECE_KNIGHT:
        return [(to_row, to_col)]

    row_step = _sign(to_row - from_row)
    col_step = _sign(to_col - from_col)

    path = []
    r, c = from_row + row_step, from_col + col_step

    while True:
        path.append((r, c))
        if (r, c) == (to_row, to_col):
            break
        r += row_step
        c += col_step

    return path

from game.model.constants import MOVE_DURATION_MS


@dataclass(frozen=True)
class MovementEvent:
    """
    A single cell-arrival event within a PendingMove's path.

    Attributes:
        sequence_id: stable identifier for the PendingMove (tie-breaker).
        piece:       the piece token.
        row:         row of the cell being entered.
        col:         column of the cell being entered.
        event_time:  clock time at which the piece arrives at this cell.
        path_index:  0-based position within the path.
        is_final:    True if this is the destination (last cell in path).
    """

    sequence_id: int
    piece: str
    row: int
    col: int
    event_time: int
    path_index: int
    is_final: bool


def decompose_moves_to_events(pending_moves):
    """
    Decompose a list of PendingMoves into chronologically sorted MovementEvents.

    Each PendingMove is broken into one event per cell in its path.
    The time for each cell is computed from started_at:
        event_time = started_at + (path_index + 1) * MOVE_DURATION_MS

    For knights (path length 1, but Chebyshev distance 2):
        The single event uses arrive_at directly.

    Events are sorted by:
        1. event_time (ascending)
        2. move_index (ascending, tie-breaker — earlier creation wins)

    Returns a list of MovementEvent sorted chronologically.
    """
    events = []

    for move_index, move in enumerate(pending_moves):
        path = compute_path(
            move.piece,
            move.from_row,
            move.from_col,
            move.to_row,
            move.to_col,
        )

        path_len = len(path)

        for path_idx, (r, c) in enumerate(path):
            is_final = (path_idx == path_len - 1)

            if path_len == 1:
                # Knight or single-step: use arrive_at directly
                event_time = move.arrive_at
            else:
                # Sliding / multi-step: uniform time per cell
                event_time = move.started_at + (path_idx + 1) * MOVE_DURATION_MS

            events.append(MovementEvent(
                sequence_id=move.sequence_id,
                piece=move.piece,
                row=r,
                col=c,
                event_time=event_time,
                path_index=path_idx,
                is_final=is_final,
            ))

    events.sort(key=lambda e: (e.event_time, e.sequence_id))
    return events
