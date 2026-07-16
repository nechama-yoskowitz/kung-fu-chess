"""
Move history observer — subscribes to MoveResolved events and records
authoritative move outcomes for display in side panels.
"""

from game.events.engine_events import MoveResolved
from game.history.move_entry import MoveEntry


_PIECE_NAMES = {
    "K": "King",
    "Q": "Queen",
    "R": "Rook",
    "B": "Bishop",
    "N": "Knight",
    "P": "Pawn",
}


class MoveHistoryObserver:
    """
    Subscribes to MoveResolved events and builds a chronological
    move history for each side.
    """

    def __init__(self, event_bus, clock_provider):
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
        return self._white_moves

    @property
    def black_entries(self) -> list[MoveEntry]:
        return self._black_moves

    def _on_move_resolved(self, event: MoveResolved) -> None:
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
        piece_name = _PIECE_NAMES.get(event.piece[1], event.piece) if len(event.piece) >= 2 else event.piece

        if event.outcome == "captured":
            return f"{piece_name} captured"

        if event.outcome == "stopped":
            return f"{piece_name} stopped at ({event.final_row},{event.final_col})"

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
        total_seconds = ms / 1000
        minutes = int(total_seconds // 60)
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:05.2f}"
