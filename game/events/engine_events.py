"""
Immutable event dataclasses published by the game engine.

These events carry authoritative resolution data so subscribers
don't need to infer outcomes from state diffs.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MoveResolved:
    """
    Published when a PendingMove is resolved (no longer in flight).

    Attributes
    ----------
    sequence_id : int
        Unique identifier matching the original PendingMove.
    piece : str
        The original piece token (e.g. "wR", "bP").
    outcome : str
        One of: "arrived", "stopped", "captured".
    final_row : int | None
        Row where the piece ended up (None if captured).
    final_col : int | None
        Column where the piece ended up (None if captured).
    promoted_to : str | None
        New piece token if promotion occurred (e.g. "wQ"), else None.
    captured_piece : str | None
        Token of the piece that was captured by this move (e.g. "bR"),
        or None if no capture occurred.
    """

    sequence_id: int
    piece: str
    outcome: str
    final_row: int | None
    final_col: int | None
    promoted_to: str | None
    captured_piece: str | None = None


@dataclass(frozen=True)
class GameEnded:
    """
    Published exactly once when a king is captured and the game ends.

    Attributes
    ----------
    winner : str
        Color of the winning side ("w" or "b").
    loser : str
        Color of the losing side ("w" or "b").
    """

    winner: str
    loser: str


@dataclass(frozen=True)
class GameStarted:
    """Published once when the game application is ready and gameplay should begin."""

    pass
