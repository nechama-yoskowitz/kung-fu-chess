"""
Client-side game state model — stores authoritative state received from the server.

Only updated from decoded server messages. Does not contain engine logic.
"""

from game.model.constants import COOLDOWN_DURATION_MS, EMPTY_CELL


def _empty_board(rows: int = 8, cols: int = 8) -> list[list[str]]:
    return [[EMPTY_CELL] * cols for _ in range(rows)]


class ClientGameState:
    """
    Lightweight state model for the network client.

    Updated only by explicit apply_* methods called from decoded server messages.
    """

    def __init__(self):
        self.board: list[list[str]] = _empty_board()
        self.clock: float = 0.0
        self.white_score: int = 0
        self.black_score: int = 0
        self.game_over: bool = False
        self.player_color: str | None = None
        self.player_username: str | None = None
        self.player_rating: int | None = None
        self.connected: bool = False
        # Active cooldowns: list of (row, col, expires_at_ms)
        self._active_cooldowns: list[tuple[int, int, float]] = []
        self._local_clock: float = 0.0

    def apply_player_assigned(self, color: str) -> None:
        """Update from a player_assigned message."""
        self.player_color = color
        self.connected = True

    def apply_login_success(self, color: str, username: str, rating: int = 1200) -> None:
        """Update from a login_success message."""
        self.player_color = color
        self.player_username = username
        self.player_rating = rating
        self.connected = True

    @property
    def player_identity_text(self) -> str | None:
        """Formatted identity string for display, or None if not logged in."""
        if self.player_username is None or self.player_color is None:
            return None
        color_name = "White" if self.player_color == "w" else "Black"
        return f"{self.player_username} | {color_name}"

    def apply_game_state(self, board: list[list[str]], clock: float,
                         white_score: int, black_score: int,
                         game_over: bool) -> None:
        """Replace the full game state from a game_state message."""
        self.board = [row[:] for row in board]  # defensive copy
        self.clock = clock
        self.white_score = white_score
        self.black_score = black_score
        self.game_over = game_over

    def apply_rating_updated(self, username: str, new_rating: int) -> None:
        """Update player_rating only if the username matches our own."""
        if self.player_username is not None and username == self.player_username:
            self.player_rating = new_rating

    def apply_move_resolved(
        self,
        from_row: int,
        from_col: int,
        piece: str,
        outcome: str,
        final_row: int | None,
        final_col: int | None,
        promoted_to: str | None,
    ) -> None:
        """
        Update the board from an authoritative move_resolved message.

        Clears the source cell and places the piece at the destination
        according to the outcome.
        """
        # Clear source cell (the piece has left)
        if 0 <= from_row < len(self.board) and 0 <= from_col < len(self.board[0]):
            self.board[from_row][from_col] = EMPTY_CELL

        if outcome == "captured":
            # Mover was destroyed — don't place anything
            return

        # Arrived or stopped — place piece at destination
        if final_row is not None and final_col is not None:
            if 0 <= final_row < len(self.board) and 0 <= final_col < len(self.board[0]):
                placed_piece = promoted_to if promoted_to else piece
                self.board[final_row][final_col] = placed_piece
                # Start a cooldown at the destination
                self._active_cooldowns.append(
                    (final_row, final_col, self._local_clock + COOLDOWN_DURATION_MS)
                )

    def advance_clock(self, delta_ms: float) -> None:
        """Advance the local clock and expire old cooldowns."""
        self._local_clock += delta_ms
        self._active_cooldowns = [
            (r, c, exp) for r, c, exp in self._active_cooldowns
            if exp > self._local_clock
        ]

    def get_cooldown_indicators(self) -> list[tuple[int, int, float]]:
        """
        Return active cooldown indicators as (row, col, progress).

        progress is 1.0 at cooldown start, 0.0 at expiry.
        """
        indicators = []
        for r, c, expires_at in self._active_cooldowns:
            remaining = expires_at - self._local_clock
            if remaining <= 0:
                continue
            progress = min(remaining / COOLDOWN_DURATION_MS, 1.0)
            indicators.append((r, c, progress))
        return indicators

    def is_piece_resting_at(self, row: int, col: int) -> bool:
        """Return True if a cooldown is active at this cell."""
        for r, c, exp in self._active_cooldowns:
            if r == row and c == col and exp > self._local_clock:
                return True
        return False
