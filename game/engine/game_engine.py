from dataclasses import dataclass

from game.model.board import is_inside_board
from game.model.constants import EMPTY_CELL
from game.realtime.real_time_arbiter import RealTimeArbiter
from game.rules.rule_engine import RuleEngine


@dataclass(frozen=True)
class MoveResult:
    """Result of a move request through the GameEngine."""

    is_accepted: bool
    reason: str


class GameEngine:
    """
    Coordinate the main game services.

    The engine is responsible for:
    - board ownership,
    - game-over state,
    - move validation through RuleEngine,
    - delegating real-time operations to RealTimeArbiter.
    """

    def __init__(self, board):
        self.board = board
        self.game_over = False
        self.rule_engine = RuleEngine()
        self.arbiter = RealTimeArbiter()

    # Read-only properties delegating to the arbiter.

    @property
    def clock(self):
        return self.arbiter.clock

    @property
    def pending_moves(self):
        return self.arbiter.pending_moves

    @property
    def active_jumps(self):
        return self.arbiter.active_jumps

    def request_move(
        self,
        from_row,
        from_col,
        to_row,
        to_col,
    ):
        """Validate and start a requested move."""
        if self.game_over:
            return MoveResult(
                is_accepted=False,
                reason="game_over",
            )

        if self.arbiter.is_destination_claimed(
            to_row,
            to_col,
        ):
            return MoveResult(
                is_accepted=False,
                reason="destination_claimed",
            )

        validation = self.rule_engine.validate_move(
            self.board,
            from_row,
            from_col,
            to_row,
            to_col,
        )

        if not validation.is_valid:
            return MoveResult(
                is_accepted=False,
                reason=validation.reason,
            )

        piece = self.board[from_row][from_col]

        self.arbiter.start_motion(
            piece,
            from_row,
            from_col,
            to_row,
            to_col,
        )

        return MoveResult(
            is_accepted=True,
            reason="ok",
        )

    def request_jump(self, row, col):
        """
        Validate and start a jump.

        Returns True if the jump was accepted,
        otherwise returns False.
        """
        if self.game_over:
            return False

        if not is_inside_board(
            self.board,
            row,
            col,
        ):
            return False

        piece = self.board[row][col]

        if piece == EMPTY_CELL:
            return False

        if self.arbiter.is_piece_moving_at(
            row,
            col,
        ):
            return False

        if self.arbiter.is_airborne_at(
            row,
            col,
        ):
            return False

        return self.arbiter.start_jump(
            piece,
            row,
            col,
        )

    def is_piece_moving_at(self, row, col):
        """Return True if the piece at the cell currently has an active move."""
        return self.arbiter.is_piece_moving_at(
            row,
            col,
        )

    def handle_wait(self, ms):
        """Advance simulated time and resolve completed actions."""
        if self.game_over:
            return

        game_over = self.arbiter.advance_time(
            self.board,
            ms,
        )

        if game_over:
            self.game_over = True

    def update_game_state(self):
        """Resolve all actions at the current clock value."""
        if self.game_over:
            return

        game_over = self.arbiter.update_state(
            self.board,
        )

        if game_over:
            self.game_over = True