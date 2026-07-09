from collections import namedtuple

from game.board import move_piece
from game.constants import PIECE_KING, PIECE_PAWN, PIECE_QUEEN, EMPTY_CELL
from game.rules import pawn_promotion_row
from game.pieces import get_type, get_color


# Represents a move that has been committed but has not yet arrived.
PendingMove = namedtuple(
    "PendingMove",
    ["piece", "from_row", "from_col", "to_row", "to_col", "arrive_at"],
)

# Represents a piece that is airborne (jumping) at a specific cell.
ActiveJump = namedtuple(
    "ActiveJump",
    ["piece", "row", "col", "expires_at"],
)


def _is_king(piece):
    """Return True if piece is a king token."""
    return len(piece) == 2 and piece[1] == PIECE_KING


def expire_jumps(active_jumps, clock):
    """Remove jumps whose expires_at < clock (they have already landed)."""
    return [j for j in active_jumps if j.expires_at >= clock]


def get_airborne_piece_at(active_jumps, row, col):
    """Return the ActiveJump at (row, col) if one exists, else None."""
    for jump in active_jumps:
        if jump.row == row and jump.col == col:
            return jump
    return None


def apply_arrived_moves(board, pending_moves, clock, active_jumps=None):
    """
    Land every pending move whose arrive_at <= clock.

    A move is cancelled if the piece is no longer at its origin square
    (another move already displaced it — first mover wins).

    If an arriving enemy encounters an airborne piece at the destination,
    the arriving piece is removed (airborne capture) and the airborne piece stays.

    Returns (still_pending, game_over, active_jumps).
    game_over is True if any arrived move captured an enemy king.
    When game_over is True, still_pending is always empty.
    """
    if active_jumps is None:
        active_jumps = []

    still_pending = []
    game_over     = False

    for move in pending_moves:
        if move.arrive_at <= clock:
            if game_over:
                continue

            # Only execute if the piece is still at its origin.
            if board[move.from_row][move.from_col] == move.piece:
                # Check for airborne enemy at the destination
                airborne = get_airborne_piece_at(active_jumps, move.to_row, move.to_col)
                if airborne is not None and airborne.piece[0] != move.piece[0]:
                    # Airborne capture: the arriving piece is destroyed.
                    # Remove the arriving piece from its source cell.
                    board[move.from_row][move.from_col] = EMPTY_CELL
                    # Check if the destroyed piece was a king.
                    if _is_king(move.piece):
                        game_over = True
                    continue

                captured = board[move.to_row][move.to_col]
                move_piece(board, move.from_row, move.from_col, move.to_row, move.to_col)

                # Promote pawn if it reached the last row
                if get_type(move.piece) == PIECE_PAWN:
                    color = get_color(move.piece)
                    if move.to_row == pawn_promotion_row(board, color):
                        board[move.to_row][move.to_col] = color + PIECE_QUEEN

                if _is_king(captured):
                    game_over = True
        else:
            if not game_over:
                still_pending.append(move)

    return still_pending, game_over, active_jumps


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
