from dataclasses import dataclass


@dataclass(frozen=True)
class MoveEntry:
    """Immutable record of a resolved move."""

    sequence_id: int
    color: str
    piece: str
    outcome: str
    final_row: int | None
    final_col: int | None
    promoted_to: str | None
    captured_piece: str | None
    timestamp_ms: float
    description: str
    time_display: str
