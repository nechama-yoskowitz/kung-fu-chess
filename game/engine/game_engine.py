from game.movement import apply_arrived_moves, expire_jumps


class GameEngine:
    """Own and update the current runtime state of the game."""

    def __init__(self, board):
        self.board = board
        self.clock = 0
        self.pending_moves = []
        self.active_jumps = []
        self.game_over = False

    def handle_wait(self, ms):
        """Advance the clock and resolve completed actions."""
        self.clock += ms

        if not self.game_over:
            self.update_game_state()

    def update_game_state(self):
        """
        Resolve all actions that should be completed at the current time.

        - Remove expired jumps.
        - Apply moves that reached their destination.
        - Clear active actions when the game ends.
        """
        self.active_jumps = expire_jumps(
            self.active_jumps,
            self.clock,
        )

        (
            self.pending_moves,
            self.game_over,
            self.active_jumps,
        ) = apply_arrived_moves(
            self.board,
            self.pending_moves,
            self.clock,
            self.active_jumps,
        )

        if self.game_over:
            self.pending_moves = []
            self.active_jumps = []