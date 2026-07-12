from game.model.constants import MOVE_DURATION_MS, JUMP_DURATION_MS
from game.realtime.motion import (
    ActiveJump,
    PendingMove,
    is_destination_claimed,
    is_piece_moving,
)
from game.realtime.movement_resolver import (
    apply_arrived_moves,
    expire_jumps,
)


class RealTimeArbiter:
    """
    Manage all real-time aspects of the game.

    Responsible for:
    - game clock
    - pending moves
    - active jumps
    - resolving completed motions
    """

    def __init__(self):
        self.clock = 0
        self.pending_moves = []
        self.active_jumps = []

    def start_motion(self, piece, from_row, from_col, to_row, to_col):
        """
        Create and store a PendingMove.

        Travel time depends on distance (Chebyshev distance × MOVE_DURATION_MS).

        Returns True if the motion was started successfully.
        """
        distance = max(abs(to_row - from_row), abs(to_col - from_col))
        pending_move = PendingMove(
            piece=piece,
            from_row=from_row,
            from_col=from_col,
            to_row=to_row,
            to_col=to_col,
            arrive_at=self.clock + distance * MOVE_DURATION_MS,
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
        self.clock += ms
        return self.update_state(board)

    def update_state(self, board):
        """
        Resolve state at the current clock without advancing time.

        - Expire completed jumps.
        - Apply arrived moves.

        Returns True if a king was captured (game over), otherwise False.
        """
        self.active_jumps = expire_jumps(self.active_jumps, self.clock)

        self.pending_moves, game_over, self.active_jumps = apply_arrived_moves(
            board,
            self.pending_moves,
            self.clock,
            self.active_jumps,
        )

        if game_over:
            self.pending_moves = []
            self.active_jumps = []

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
