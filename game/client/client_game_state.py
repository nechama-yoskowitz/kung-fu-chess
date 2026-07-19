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
        self.connected: bool = False

    def apply_player_assigned(self, color: str) -> None:
        """Update from a player_assigned message."""
        self.player_color = color
        self.connected = True

    def apply_game_state(self, board: list[list[str]], clock: float,
                         white_score: int, black_score: int,
                         game_over: bool) -> None:
        """Replace the full game state from a game_state message."""
        self.board = [row[:] for row in board]  # defensive copy
        self.clock = clock
        self.white_score = white_score
        self.black_score = black_score
        self.game_over = game_over
