from game.graphics.animation import Animation
from game.graphics.sprite_manager import SpriteManager
from game.graphics.piece_state_machine import PieceStateMachine

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

        self.state_machine = PieceStateMachine(initial_state)

        self.animation = self._create_animation(
            self.state_machine.current_state
        )

    def _create_animation(self, state: str) -> Animation:
        animation_data = self.sprite_manager.get_animation_data(
            piece=self.piece,
            state=state,
            size=self.piece_size,
        )

        return Animation(animation_data)

    def update(self, delta_time_ms: float) -> None:
        self.animation.update(delta_time_ms)

        if not self.animation.is_finished():
            return

        if self.state == PieceStateMachine.JUMP:
            self.set_state(PieceStateMachine.IDLE)

        elif self.state == PieceStateMachine.SHORT_REST:
            self.set_state(PieceStateMachine.IDLE)

        elif self.state == PieceStateMachine.LONG_REST:
            self.set_state(PieceStateMachine.IDLE)

        def get_current_frame(self):
            return self.animation.get_current_frame()

    def set_state(self, new_state: str) -> None:
        state_changed = self.state_machine.transition_to(new_state)

        if not state_changed:
            return

        self.animation = self._create_animation(
            self.state_machine.current_state
        )

    def set_position(self, row: int, col: int) -> None:
        self.row = row
        self.col = col

    @property
    def state(self) -> str:
        return self.state_machine.current_state    