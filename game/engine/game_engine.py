from game.board import is_inside_board
from game.constants import (
    EMPTY_CELL,
    JUMP_DURATION_MS,
    MOVE_DURATION_MS,
)
from game.movement import (
    ActiveJump,
    PendingMove,
    apply_arrived_moves,
    expire_jumps,
    is_destination_claimed,
    is_piece_moving,
)
from game.rules.rule_engine import RuleEngine


class GameEngine:
    """
    Own and update the current runtime state of the game.

    The engine is responsible for:
    - validating move requests,
    - starting moves and jumps,
    - advancing time,
    - resolving arrivals,
    - maintaining game-over state.
    """

    def __init__(self, board):
        self.board = board
        self.clock = 0
        self.pending_moves = []
        self.active_jumps = []
        self.game_over = False
        self.rule_engine = RuleEngine()

    def request_move(
        self,
        from_row,
        from_col,
        to_row,
        to_col,
    ):
        """
        Validate and start a requested move.

        Returns True if the move was accepted,
        otherwise returns False.
        """
        if self.game_over:
            return False

        if is_destination_claimed(
            self.pending_moves,
            to_row,
            to_col,
        ):
            return False

        if not self.rule_engine.validate_move(
            self.board,
            from_row,
            from_col,
            to_row,
            to_col,
        ):
            return False

        piece = self.board[from_row][from_col]

        pending_move = PendingMove(
            piece=piece,
            from_row=from_row,
            from_col=from_col,
            to_row=to_row,
            to_col=to_col,
            arrive_at=self.clock + MOVE_DURATION_MS,
        )

        self.pending_moves.append(pending_move)
        return True

    def request_jump(self, row, col):
        """
        Validate and start a jump.

        Returns True if the jump was accepted,
        otherwise returns False.
        """
        if self.game_over:
            return False

        if not is_inside_board(self.board, row, col):
            return False

        piece = self.board[row][col]

        if piece == EMPTY_CELL:
            return False

        if is_piece_moving(
            self.pending_moves,
            row,
            col,
        ):
            return False

        if self._is_airborne(row, col):
            return False

        jump = ActiveJump(
            piece=piece,
            row=row,
            col=col,
            expires_at=self.clock + JUMP_DURATION_MS,
        )

        self.active_jumps.append(jump)
        return True

    def is_piece_moving_at(self, row, col):
        """Return True if the piece at the cell currently has an active move."""
        return is_piece_moving(
            self.pending_moves,
            row,
            col,
        )

    def handle_wait(self, ms):
        """Advance the clock and resolve completed actions."""
        self.clock += ms

        if not self.game_over:
            self.update_game_state()

    def update_game_state(self):
        """
        Resolve all actions that should finish at the current time.

        - Remove expired jumps.
        - Apply moves that reached their destination.
        - Clear active actions when the game ends.
        """
        if self.game_over:
            return

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

    def _is_airborne(self, row, col):
        """Return True if the piece at the cell is currently airborne."""
        return any(
            jump.row == row and jump.col == col
            for jump in self.active_jumps
        )