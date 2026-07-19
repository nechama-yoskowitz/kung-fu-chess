"""
NetworkGameGateway — sends commands to the remote server via the outgoing queue.

Implements GameCommandGateway so the Controller works identically to local mode.

Key difference: request_move/request_jump cannot know server acceptance synchronously.
They return MoveRequestResult(is_accepted=False, reason="pending") to indicate
the command was submitted but not yet confirmed by the server.
"""

import queue

from game.controller.game_gateway import GameCommandGateway, MoveRequestResult
from game.client.client_game_state import ClientGameState
from game.server.protocol import make_move_request, make_jump_request

# Returned when a command is queued for the server but not yet confirmed.
_PENDING_RESULT = MoveRequestResult(is_accepted=False, reason="pending")


class NetworkGameGateway(GameCommandGateway):
    """
    Gateway that queues commands for a remote server.

    Board queries read from ClientGameState (populated by server messages).
    Move/jump commands are queued for network dispatch — not executed locally.
    """

    def __init__(self, state: ClientGameState, outgoing: queue.Queue):
        self._state = state
        self._outgoing = outgoing

    @property
    def board(self) -> list[list[str]]:
        return self._state.board

    def is_piece_moving_at(self, row: int, col: int) -> bool:
        # Without local engine tracking, we cannot know with certainty.
        # Return False to allow selection. The server will reject invalid moves.
        return False

    def is_piece_resting_at(self, row: int, col: int) -> bool:
        # Same rationale — rely on server rejection for accuracy.
        return False

    def request_move(self, from_row: int, from_col: int,
                     to_row: int, to_col: int) -> MoveRequestResult:
        """Queue a move_request message. Returns pending (not accepted)."""
        msg = make_move_request(from_row, from_col, to_row, to_col)
        self._outgoing.put_nowait(msg)
        return _PENDING_RESULT

    def request_jump(self, row: int, col: int) -> bool:
        """Queue a jump_request message. Returns False (pending, not confirmed)."""
        msg = make_jump_request(row, col)
        self._outgoing.put_nowait(msg)
        return False
