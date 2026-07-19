"""
GameCommandGateway — abstraction that decouples the Controller from
knowing whether commands are handled locally or remotely.

The Controller depends on this interface. Implementations:
- LocalGameGateway: delegates to a real GameEngine (current local mode)
- Future: NetworkGameGateway: sends protocol messages to a server
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MoveRequestResult:
    """Result of a move request through any gateway."""

    is_accepted: bool
    reason: str


class GameCommandGateway:
    """
    Abstract interface for game commands and board queries.

    The Controller calls these methods without knowing whether
    the game is local or remote.
    """

    @property
    def board(self) -> list[list[str]]:
        raise NotImplementedError

    @property
    def player_color(self) -> str | None:
        """
        The color this client controls ('w' or 'b'), or None if unrestricted.

        When set, the Controller should only allow selecting pieces of this color.
        Local mode returns None (both colors playable).
        """
        return None

    def is_piece_moving_at(self, row: int, col: int) -> bool:
        raise NotImplementedError

    def is_piece_resting_at(self, row: int, col: int) -> bool:
        raise NotImplementedError

    def request_move(self, from_row: int, from_col: int,
                     to_row: int, to_col: int) -> MoveRequestResult:
        raise NotImplementedError

    def request_jump(self, row: int, col: int) -> bool:
        raise NotImplementedError
