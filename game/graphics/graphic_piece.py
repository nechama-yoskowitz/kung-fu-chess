from game.graphics.animation import Animation
from game.graphics.sprite_manager import SpriteManager


class GraphicPiece:
    def __init__(
        self,
        piece: str,
        row: int,
        col: int,
        sprite_manager: SpriteManager,
        piece_size: tuple[int, int],
        initial_state: str = "idle",
    ):
        self.piece = piece
        self.row = row
        self.col = col

        self.sprite_manager = sprite_manager
        self.piece_size = piece_size

        self.state = initial_state
        self.animation = self._create_animation(initial_state)

    def _create_animation(self, state: str) -> Animation:
        animation_data = self.sprite_manager.get_animation_data(
            piece=self.piece,
            state=state,
            size=self.piece_size,
        )

        return Animation(animation_data)

    def update(self, delta_time_ms: float) -> None:
        self.animation.update(delta_time_ms)

    def get_current_frame(self):
        return self.animation.get_current_frame()

    def set_state(self, new_state: str) -> None:
        if new_state == self.state:
            return

        self.state = new_state
        self.animation = self._create_animation(new_state)

    def set_position(self, row: int, col: int) -> None:
        self.row = row
        self.col = col