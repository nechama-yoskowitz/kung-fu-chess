from game.graphics.animation import Animation
from game.graphics.sprite_manager import SpriteManager


class BoardAnimations:
    def __init__(
        self,
        sprite_manager: SpriteManager,
        piece_size: tuple[int, int],
    ):
        self.sprite_manager = sprite_manager
        self.piece_size = piece_size
        self._animations = {}

    def initialize(self, board, state: str = "idle") -> None:
        self._animations.clear()

        for row, board_row in enumerate(board):
            for col, piece in enumerate(board_row):
                if piece == ".":
                    continue

                data = self.sprite_manager.get_animation_data(
                    piece=piece,
                    state=state,
                    size=self.piece_size,
                )

                self._animations[(row, col)] = Animation(data)

    def update(self, delta_time_ms: float) -> None:
        for animation in self._animations.values():
            animation.update(delta_time_ms)

    def get_current_frame(self, row: int, col: int):
        animation = self._animations.get((row, col))

        if animation is None:
            return None

        return animation.get_current_frame()