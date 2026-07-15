class GraphicMovement:
    """
    Encapsulates the interpolation logic for a piece moving
    between two board positions over a fixed duration.

    Responsibilities:
    - Storing movement endpoints and timing
    - Advancing elapsed time and computing progress
    - Producing the interpolated (row, col) at any point
    - Detecting when the movement is complete
    """

    def __init__(self):
        self._start_row = 0.0
        self._start_col = 0.0
        self._target_row = 0.0
        self._target_col = 0.0

        self._elapsed_ms = 0.0
        self._duration_ms = 0.0
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def target_row(self) -> float:
        return self._target_row

    @property
    def target_col(self) -> float:
        return self._target_col

    def start(
        self,
        from_row: float,
        from_col: float,
        to_row: int,
        to_col: int,
        duration_ms: float,
    ) -> None:
        """Begin a new movement from the current display position to a target cell."""
        if duration_ms <= 0:
            raise ValueError("duration_ms must be greater than zero")

        if self._active:
            raise RuntimeError("Movement is already in progress")

        self._start_row = from_row
        self._start_col = from_col
        self._target_row = float(to_row)
        self._target_col = float(to_col)

        self._elapsed_ms = 0.0
        self._duration_ms = duration_ms
        self._active = True

    def cancel(self) -> None:
        """Cancel the active movement without producing a final position."""
        self._active = False
        self._elapsed_ms = 0.0

    def update(self, delta_time_ms: float) -> tuple[float, float, bool]:
        """
        Advance the movement by delta_time_ms.

        Returns:
            (display_row, display_col, finished)
            - The interpolated position after this tick.
            - finished is True if the movement completed on this tick.
        """
        if not self._active:
            raise RuntimeError("No active movement to update")

        self._elapsed_ms += delta_time_ms

        progress = min(self._elapsed_ms / self._duration_ms, 1.0)

        display_row = (
            self._start_row
            + (self._target_row - self._start_row) * progress
        )

        display_col = (
            self._start_col
            + (self._target_col - self._start_col) * progress
        )

        finished = progress >= 1.0

        if finished:
            display_row = self._target_row
            display_col = self._target_col
            self._active = False
            self._elapsed_ms = 0.0

        return display_row, display_col, finished
