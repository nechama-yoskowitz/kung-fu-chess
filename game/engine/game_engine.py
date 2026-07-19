from dataclasses import dataclass

from game.events import EventBus
from game.events.engine_events import GameEnded, MoveResolved
from game.model.constants import PIECE_VALUES
from game.model.pieces import get_color, get_type, is_king
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
    - delegating real-time operations to RealTimeArbiter,
    - hosting the event bus for decoupled communication,
    - tracking material score.
    """

    def __init__(self, board, event_bus=None):
        self.board = board
        self.game_over = False
        self.event_bus = event_bus or EventBus()
        self.rule_engine = RuleEngine()
        self.arbiter = RealTimeArbiter(event_bus=self.event_bus)
        self._white_score = 0
        self._black_score = 0
        self._pending_game_end: tuple[str, str] | None = None  # (winner, loser)

        self.event_bus.subscribe(MoveResolved, self._on_move_resolved)

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

    @property
    def active_cooldowns(self):
        return self.arbiter.active_cooldowns

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

        if self.arbiter.is_piece_resting_at(from_row, from_col):
            return MoveResult(
                is_accepted=False,
                reason="piece_resting",
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

        if self.arbiter.is_piece_resting_at(row, col):
            return False

        validation = self.rule_engine.validate_jump(
            self.board,
            row,
            col,
            is_piece_moving=self.arbiter.is_piece_moving_at(row, col),
            is_airborne=self.arbiter.is_airborne_at(row, col),
        )

        if not validation.is_valid:
            return False

        piece = self.board[row][col]
        return self.arbiter.start_jump(piece, row, col)

    def is_piece_moving_at(self, row, col):
        """Return True if the piece at the cell currently has an active move."""
        return self.arbiter.is_piece_moving_at(
            row,
            col,
        )

    def is_piece_resting_at(self, row, col):
        """Return True if the piece at the cell is in cooldown."""
        return self.arbiter.is_piece_resting_at(row, col)

    def handle_wait(self, ms):
        """Advance simulated time and resolve completed actions."""
        if self.game_over:
            return

        game_over = self.arbiter.advance_time(
            self.board,
            ms,
        )

        if game_over:
            self._transition_to_game_over()

    def update_game_state(self):
        """Resolve all actions at the current clock value."""
        if self.game_over:
            return

        game_over = self.arbiter.update_state(
            self.board,
        )

        if game_over:
            self._transition_to_game_over()

    def _transition_to_game_over(self) -> None:
        """Set game_over flag and publish GameEnded exactly once."""
        self.game_over = True
        if self._pending_game_end:
            winner, loser = self._pending_game_end
            self.event_bus.publish(GameEnded(winner=winner, loser=loser))

    @property
    def white_score(self):
        """Total material captured by white."""
        return self._white_score

    @property
    def black_score(self):
        """Total material captured by black."""
        return self._black_score

    def _on_move_resolved(self, event: MoveResolved) -> None:
        """Update score and detect king capture for game-end tracking."""
        if not event.captured_piece:
            return

        captured_type = get_type(event.captured_piece)
        captured_color = get_color(event.captured_piece)

        # Track king capture for GameEnded event (published later by _transition_to_game_over)
        if is_king(event.captured_piece):
            loser = captured_color
            winner = "w" if loser == "b" else "b"
            self._pending_game_end = (winner, loser)
            return  # King has value 0, no score update needed

        value = PIECE_VALUES.get(captured_type, 0)

        if value == 0:
            return

        if captured_color == "b":
            self._white_score += value
        else:
            self._black_score += value
