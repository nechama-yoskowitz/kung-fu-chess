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
    """

    sequence_id: int
    piece: str
    outcome: str
    final_row: int | None
    final_col: int | None
    promoted_to: str | None
