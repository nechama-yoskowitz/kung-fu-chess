"""
Move history observer — subscribes to MoveResolved events and records
authoritative move outcomes for display in side panels.

This is a pure Observer: it listens to engine events, records history,
and exposes read-only data to the UI. It does not modify the engine,
graphics, or game rules.
"""

from dataclasses import dataclass

from game.events.engine_events import MoveResolved


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


class MoveHistoryObserver:
    """
    Subscribes to MoveResolved events and builds a chronological
    move history for each side.

    The engine clock at event publish time is used as the timestamp.
    """

    def __init__(self, event_bus, clock_provider):
        """
        Parameters
        ----------
        event_bus : EventBus
            The bus to subscribe to.
        clock_provider : callable
            Returns the current engine clock (ms) when called.
        """
        self._white_moves: list[MoveEntry] = []
        self._black_moves: list[MoveEntry] = []
        self._seen_sequence_ids: set[int] = set()
        self._clock_provider = clock_provider

        event_bus.subscribe(MoveResolved, self._on_move_resolved)

    @property
    def white_moves(self) -> list[dict]:
        """Read-only view for the UI (list of {time, move} dicts)."""
        return [{"time": e.time_display, "move": e.description} for e in self._white_moves]

    @property
    def black_moves(self) -> list[dict]:
        """Read-only view for the UI (list of {time, move} dicts)."""
        return [{"time": e.time_display, "move": e.description} for e in self._black_moves]

    @property
    def white_entries(self) -> list[MoveEntry]:
        """Full structured entries for white."""
        return self._white_moves

    @property
    def black_entries(self) -> list[MoveEntry]:
        """Full structured entries for black."""
        return self._black_moves

    def _on_move_resolved(self, event: MoveResolved) -> None:
        """Handle a MoveResolved event — record the move outcome."""
        # Prevent duplicate entries for the same sequence_id
        if event.sequence_id in self._seen_sequence_ids:
            return
        self._seen_sequence_ids.add(event.sequence_id)

        clock_ms = self._clock_provider()
        color = event.piece[0] if len(event.piece) >= 2 else "w"
        description = self._build_description(event)
        time_display = self._format_time(clock_ms)

        entry = MoveEntry(
            sequence_id=event.sequence_id,
            color=color,
            piece=event.piece,
            outcome=event.outcome,
            final_row=event.final_row,
            final_col=event.final_col,
            promoted_to=event.promoted_to,
            captured_piece=event.captured_piece,
            timestamp_ms=clock_ms,
            description=description,
            time_display=time_display,
        )

        if color == "w":
            self._white_moves.append(entry)
        else:
            self._black_moves.append(entry)

    @staticmethod
    def _build_description(event: MoveResolved) -> str:
        """Build a readable move description from the event."""
        piece_name = _PIECE_NAMES.get(event.piece[1], event.piece) if len(event.piece) >= 2 else event.piece

        if event.outcome == "captured":
            return f"{piece_name} captured"

        if event.outcome == "stopped":
            return f"{piece_name} stopped at ({event.final_row},{event.final_col})"

        # Arrived
        desc = f"{piece_name} -> ({event.final_row},{event.final_col})"

        if event.promoted_to:
            promoted_name = _PIECE_NAMES.get(event.promoted_to[1], event.promoted_to)
            desc += f" = {promoted_name}"

        if event.captured_piece:
            captured_name = _PIECE_NAMES.get(event.captured_piece[1], event.captured_piece)
            desc += f" x{captured_name}"

        return desc

    @staticmethod
    def _format_time(ms: float) -> str:
        """Format milliseconds as MM:SS.mmm."""
        total_seconds = ms / 1000
        minutes = int(total_seconds // 60)
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:05.2f}"


_PIECE_NAMES = {
    "K": "King",
    "Q": "Queen",
    "R": "Rook",
    "B": "Bishop",
    "N": "Knight",
    "P": "Pawn",
}
