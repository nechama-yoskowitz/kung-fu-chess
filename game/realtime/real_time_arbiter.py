from game.model.constants import MOVE_DURATION_MS, JUMP_DURATION_MS, COOLDOWN_DURATION_MS
from game.realtime.motion import (
    ActiveCooldown,
    ActiveJump,
    PendingMove,
    is_destination_claimed,
    is_piece_moving,
    is_piece_resting,
)
from game.realtime.movement_resolver import (
    expire_jumps,
    resolve_window,
)


class RealTimeArbiter:
    """
    Manage all real-time aspects of the game.

    Responsible for:
    - game clock
    - pending moves
    - active jumps
    - active cooldowns
    - resolving completed motions
    """

    def __init__(self, event_bus=None):
        self.clock = 0
        self.pending_moves = []
        self.active_jumps = []
        self.active_cooldowns = []
        self._next_sequence_id = 0
        self._event_bus = event_bus

    def start_motion(self, piece, from_row, from_col, to_row, to_col):
        """
        Create and store a PendingMove.

        Travel time depends on distance (Chebyshev distance × MOVE_DURATION_MS).

        Returns True if the motion was started successfully.
        """
        distance = max(abs(to_row - from_row), abs(to_col - from_col))
        seq_id = self._next_sequence_id
        self._next_sequence_id += 1
        pending_move = PendingMove(
            piece=piece,
            from_row=from_row,
            from_col=from_col,
            to_row=to_row,
            to_col=to_col,
            started_at=self.clock,
            arrive_at=self.clock + distance * MOVE_DURATION_MS,
            sequence_id=seq_id,
        )
        self.pending_moves.append(pending_move)
        return True

    def start_jump(self, piece, row, col):
        """
        Create and store an ActiveJump.

        Returns True if the jump was started successfully.
        """
        jump = ActiveJump(
            piece=piece,
            row=row,
            col=col,
            expires_at=self.clock + JUMP_DURATION_MS,
        )
        self.active_jumps.append(jump)
        return True

    def advance_time(self, board, ms):
        """
        Advance the clock by ms milliseconds, then resolve state.

        Returns True if resolving arrivals caused game over.
        """
        previous_clock = self.clock
        self.clock += ms
        return self._resolve(board, previous_clock, self.clock)

    def update_state(self, board):
        """
        Resolve state at the current clock without advancing time.

        With an empty window (prev == curr), no new events are processed.
        Only expires jumps and cooldowns.

        Returns True if a king was captured (game over), otherwise False.
        """
        return self._resolve(board, self.clock, self.clock)

    def _resolve(self, board, prev_clock, curr_clock):
        """
        Internal resolution for a time window.

        Expires jumps and cooldowns, then processes movement events
        in the window (prev_clock, curr_clock].
        """
        self.active_jumps = expire_jumps(self.active_jumps, curr_clock)
        self.expire_cooldowns()

        if prev_clock == curr_clock:
            return False

        self.pending_moves, game_over, self.active_jumps, arrived_cells, resolved_moves = (
            resolve_window(
                board,
                self.pending_moves,
                prev_clock,
                curr_clock,
                self.active_jumps,
            )
        )

        # Publish authoritative resolution events before any further state changes.
        if self._event_bus and resolved_moves:
            from game.events.engine_events import MoveResolved
            for rm in resolved_moves:
                self._event_bus.publish(MoveResolved(
                    sequence_id=rm["sequence_id"],
                    piece=rm["piece"],
                    outcome=rm["outcome"],
                    final_row=rm["final_row"],
                    final_col=rm["final_col"],
                    promoted_to=rm["promoted_to"],
                ))

        if game_over:
            self.pending_moves = []
            self.active_jumps = []
            self.active_cooldowns = []
        else:
            for piece, row, col in arrived_cells:
                self.start_cooldown(piece, row, col)

        return game_over

    def is_piece_moving_at(self, row, col):
        """Return True if the piece at (row, col) has a pending move."""
        return is_piece_moving(self.pending_moves, row, col)

    def has_active_motion(self):
        """Return True if there are any pending moves in flight."""
        return len(self.pending_moves) > 0

    def is_airborne_at(self, row, col):
        """Return True if the piece at (row, col) is currently airborne."""
        return any(
            jump.row == row and jump.col == col
            for jump in self.active_jumps
        )

    def is_destination_claimed(self, row, col):
        """Return True if a pending move is already heading to (row, col)."""
        return is_destination_claimed(self.pending_moves, row, col)

    def start_cooldown(self, piece, row, col):
        """Start a cooldown for a piece that just arrived at (row, col)."""
        cooldown = ActiveCooldown(
            piece=piece,
            row=row,
            col=col,
            available_at=self.clock + COOLDOWN_DURATION_MS,
        )
        self.active_cooldowns.append(cooldown)

    def is_piece_resting_at(self, row, col):
        """Return True if a piece at (row, col) is currently in cooldown."""
        for cd in self.active_cooldowns:
            if cd.row == row and cd.col == col and cd.available_at > self.clock:
                return True
        return False

    def expire_cooldowns(self):
        """Remove cooldowns that have expired (available_at <= clock)."""
        self.active_cooldowns = [
            cd for cd in self.active_cooldowns
            if cd.available_at > self.clock
        ]
