from collections import namedtuple

from game.board import move_piece
from game.constants import PIECE_KING, PIECE_PAWN, PIECE_QUEEN
from game.rules import pawn_promotion_row
from game.pieces import get_type, get_color


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


def _is_king(piece):
    """Return True if piece is a king token."""
    return len(piece) == 2 and piece[1] == PIECE_KING


def apply_arrived_moves(board, pending_moves, clock):
    """
    Land every pending move whose arrive_at <= clock.

    A move is cancelled if the piece is no longer at its origin square
    (another move already displaced it — first mover wins).

    Returns (still_pending, game_over).
    game_over is True if any arrived move captured an enemy king.
    When game_over is True, still_pending is always empty.
    """
    still_pending = []
    game_over     = False

    for move in pending_moves:
        if move.arrive_at <= clock:
            if game_over:
                # Game already ended — discard all remaining moves.
                continue

            # Only execute if the piece is still at its origin.
            if board[move.from_row][move.from_col] == move.piece:
                captured = board[move.to_row][move.to_col]
                move_piece(board, move.from_row, move.from_col, move.to_row, move.to_col)

                # Promote pawn if it reached the last row
                if get_type(move.piece) == PIECE_PAWN:
                    color = get_color(move.piece)
                    if move.to_row == pawn_promotion_row(board, color):
                        board[move.to_row][move.to_col] = color + PIECE_QUEEN

                if _is_king(captured):
                    game_over = True
                    # still_pending stays empty — all remaining moves cancelled.
        else:
            if not game_over:
                still_pending.append(move)

    return still_pending, game_over


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
