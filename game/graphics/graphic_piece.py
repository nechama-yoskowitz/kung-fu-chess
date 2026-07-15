from game.graphics.animation import Animation
from game.graphics.graphic_movement import GraphicMovement
from game.graphics.sprite_manager import SpriteManager
from game.graphics.piece_state_machine import PieceStateMachine

class GraphicPiece:
    
    @property
    def state(self) -> str:
        return self.state_machine.current_state    

    @property
    def is_moving(self) -> bool:
        return self._movement.is_active

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
        self.display_row = float(row)
        self.display_col = float(col)

        self._movement = GraphicMovement()

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

        if self.is_moving:
            self._update_movement(delta_time_ms)

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
        self.display_row = float(row)
        self.display_col = float(col)

    def start_move(
    self,
    to_row: int,
    to_col: int,
    duration_ms: float,
    ) -> None:
        self._movement.start(
            from_row=self.display_row,
            from_col=self.display_col,
            to_row=to_row,
            to_col=to_col,
            duration_ms=duration_ms,
        )

        self.set_state(PieceStateMachine.MOVE)

    def _update_movement(self, delta_time_ms: float) -> None:
        display_row, display_col, finished = self._movement.update(
            delta_time_ms
        )

        self.display_row = display_row
        self.display_col = display_col

        if finished:
            self._finish_move()

    def _finish_move(self) -> None:
        self.row = int(self._movement.target_row)
        self.col = int(self._movement.target_col)

        self.set_state(PieceStateMachine.LONG_REST)

    def finish_move_at(self, row: int, col: int) -> None:
        """
        Authoritatively end movement and place the piece at the given cell.

        Called by the synchronizer when the engine has resolved a move.
        If the graphic movement is still active, it is cancelled.
        The piece is snapped to the destination with correct state.
        """
        if self._movement.is_active:
            self._movement.cancel()

        self.row = row
        self.col = col
        self.display_row = float(row)
        self.display_col = float(col)

        if self.state == PieceStateMachine.MOVE:
            self.set_state(PieceStateMachine.LONG_REST)
