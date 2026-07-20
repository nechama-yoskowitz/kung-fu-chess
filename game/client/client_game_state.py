"""
Client-side game state model — stores authoritative state received from the server.

Only updated from decoded server messages. Does not contain engine logic.
"""

from game.model.constants import EMPTY_CELL


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
