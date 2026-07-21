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
        self.opponent_username: str | None = None
        self.connected: bool = False
        # Room/matchmaking state
        self.room_id: str | None = None
        self.room_role: str | None = None  # "player" or "viewer"
        self.is_viewer: bool = False
        self.matchmaking_active: bool = False
        # Reconnect state
        self.disconnected_player: str | None = None  # username of disconnected player
        self.disconnected_color: str | None = None
        self.reconnect_remaining: int | None = None  # seconds
        # Game result
        self.game_end_reason: str | None = None  # e.g. "checkmate", "auto_resign"
        self.winner_color: str | None = None
        # Active cooldowns: list of (row, col, expires_at_ms)
        self._active_cooldowns: list[tuple[int, int, float]] = []
        self._local_clock: float = 0.0

    def apply_player_assigned(self, color: str) -> None:
        """Update from a player_assigned message."""
        self.player_color = color
        self.connected = True

    def apply_login_success(self, color: str | None, username: str, rating: int = 1200) -> None:
        """Update from a login_success message."""
        if color:
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

    def apply_match_found(self, payload: dict) -> None:
        """Store match information from a match_found message."""
        self.opponent_username = payload.get("opponent_username")
        color = payload.get("color")
        if color:
            self.player_color = color
        self.matchmaking_active = False

    def apply_matchmaking_started(self) -> None:
        """Mark that matchmaking is active."""
        self.matchmaking_active = True

    def apply_matchmaking_ended(self) -> None:
        """Mark that matchmaking ended (timeout or cancelled)."""
        self.matchmaking_active = False

    def apply_room_created(self, room_id: str) -> None:
        """Store room creation info."""
        self.room_id = room_id
        self.room_role = "player"

    def apply_room_joined(self, room_id: str, role: str, color: str | None) -> None:
        """Store room join info."""
        self.room_id = room_id
        self.room_role = role
        self.is_viewer = (role == "viewer")
        if color:
            self.player_color = color

    def apply_player_disconnected(self, username: str, color: str, remaining: int) -> None:
        """A player disconnected — store for display."""
        self.disconnected_player = username
        self.disconnected_color = color
        self.reconnect_remaining = remaining

    def apply_reconnect_countdown(self, remaining: int) -> None:
        """Update the reconnect countdown seconds."""
        self.reconnect_remaining = remaining

    def apply_player_reconnected(self, username: str) -> None:
        """A player reconnected — clear disconnect state."""
        self.disconnected_player = None
        self.disconnected_color = None
        self.reconnect_remaining = None

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
