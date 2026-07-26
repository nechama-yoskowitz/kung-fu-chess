"""
Immutable event dataclasses published by the game engine.

These events carry authoritative resolution data so subscribers
don't need to infer outcomes from state diffs.
"""

from dataclasses import dataclass
from enum import Enum

from game.model.piece import Piece, PieceColor


class MoveOutcome(str, Enum):
    """
    Possible outcomes when a PendingMove is resolved.

    Inherits from str so that serialization to JSON produces the bare
    string value ("arrived", "stopped", "captured") without extra conversion.
    """
    ARRIVED = "arrived"
    STOPPED = "stopped"
    CAPTURED = "captured"


@dataclass(frozen=True)
class MoveResolved:
    """
    Published when a PendingMove is resolved (no longer in flight).

    Attributes
    ----------
    sequence_id : int
        Unique identifier matching the original PendingMove.
    piece : Piece
        The original piece that was moving.
    outcome : MoveOutcome
        Resolution result.
    final_row : int | None
        Row where the piece ended up (None if captured).
    final_col : int | None
        Column where the piece ended up (None if captured).
    promoted_to : Piece | None
        New Piece if promotion occurred, else None.
    captured_piece : Piece | None
        The piece that was captured by this move, or None.
    """

    sequence_id: int
    piece: Piece
    outcome: MoveOutcome
    final_row: int | None
    final_col: int | None
    promoted_to: Piece | None
    captured_piece: Piece | None = None


@dataclass(frozen=True)
class GameEnded:
    """
    Published exactly once when a king is captured and the game ends.

    Attributes
    ----------
    winner : PieceColor
        Color of the winning side.
    loser : PieceColor
        Color of the losing side.
    """

    winner: PieceColor
    loser: PieceColor


@dataclass(frozen=True)
class GameStarted:
    """Published once when the game application is ready and gameplay should begin."""

    pass
