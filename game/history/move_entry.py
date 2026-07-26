from dataclasses import dataclass

from game.events.engine_events import MoveOutcome
from game.model.piece import Piece, PieceColor


@dataclass(frozen=True)
class MoveEntry:
    """Immutable record of a resolved move."""

    sequence_id: int
    color: PieceColor
    piece: Piece
    outcome: MoveOutcome
    final_row: int | None
    final_col: int | None
    promoted_to: Piece | None
    captured_piece: Piece | None
    timestamp_ms: float
    description: str
    time_display: str
