"""
LocalGameGateway — delegates all commands to a real local GameEngine.

Used in local/offline mode. The Controller interacts with this gateway
identically to how it would interact with a future NetworkGameGateway.
"""

from game.controller.game_gateway import GameCommandGateway, MoveRequestResult
from game.engine.game_engine import GameEngine


class LocalGameGateway(GameCommandGateway):
    """Wraps a local GameEngine as a GameCommandGateway."""

    def __init__(self, engine: GameEngine):
        self._engine = engine

    @property
    def board(self) -> list[list[str]]:
        return self._engine.board

    def is_piece_moving_at(self, row: int, col: int) -> bool:
        return self._engine.is_piece_moving_at(row, col)

    def is_piece_resting_at(self, row: int, col: int) -> bool:
        return self._engine.is_piece_resting_at(row, col)

    def request_move(self, from_row: int, from_col: int,
                     to_row: int, to_col: int) -> MoveRequestResult:
        result = self._engine.request_move(from_row, from_col, to_row, to_col)
        return MoveRequestResult(
            is_accepted=result.is_accepted,
            reason=result.reason,
        )

    def request_jump(self, row: int, col: int) -> bool:
        return self._engine.request_jump(row, col)
