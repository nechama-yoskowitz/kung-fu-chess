"""
Move history model — records accepted moves for display in side panels.

Owned by the application layer, not by graphics or engine internals.
"""


class MoveHistory:
    """
    Records move entries for display. Each entry has a color, timestamp,
    and a simple move description.
    """

    def __init__(self):
        self._white_moves: list[dict] = []
        self._black_moves: list[dict] = []

    @property
    def white_moves(self) -> list[dict]:
        return self._white_moves

    @property
    def black_moves(self) -> list[dict]:
        return self._black_moves

    def record_move(self, color: str, clock_ms: float,
                    piece: str, from_row: int, from_col: int,
                    to_row: int, to_col: int) -> None:
        """
        Record a move entry.

        Parameters
        ----------
        color : str
            "w" or "b".
        clock_ms : float
            Engine clock at the time the move was requested.
        piece : str
            Piece token (e.g. "wR").
        from_row, from_col : int
            Source cell.
        to_row, to_col : int
            Destination cell.
        """
        time_str = self._format_time(clock_ms)
        move_str = f"{piece[1]}({from_row},{from_col})->({to_row},{to_col})"

        entry = {"time": time_str, "move": move_str}

        if color == "w":
            self._white_moves.append(entry)
        else:
            self._black_moves.append(entry)

    @staticmethod
    def _format_time(ms: float) -> str:
        """Format milliseconds as MM:SS.mmm."""
        total_seconds = ms / 1000
        minutes = int(total_seconds // 60)
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:06.3f}"
