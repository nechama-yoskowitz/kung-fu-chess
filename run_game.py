"""
Kung-Fu Chess — interactive graphical launcher.

This is the application entry point. It wires together the engine,
controller, graphics, and input layers, then runs the game loop.
"""

from game.controller.controller import Controller
from game.engine.game_engine import GameEngine
from game.graphics.frame_composer import FrameComposer
from game.graphics.game_loop import GameLoop
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.graphics_synchronizer import GraphicsSynchronizer
from game.graphics.mouse_input_adapter import MouseInputAdapter
from game.graphics.renderer import Renderer
from game.graphics.sprite_manager import SpriteManager
from game.model.board_mapper import BoardMapper
from game.model.constants import COOLDOWN_DURATION_MS


STARTING_BOARD = [
    ["bR", "bN", "bB", "bQ", "bK", "bB", "bN", "bR"],
    ["bP", "bP", "bP", "bP", "bP", "bP", "bP", "bP"],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    ["wP", "wP", "wP", "wP", "wP", "wP", "wP", "wP"],
    ["wR", "wN", "wB", "wQ", "wK", "wB", "wN", "wR"],
]

BOARD_IMAGE_PATH = "game/graphics/assets/board.png"
PIECES_ROOT_PATH = "game/graphics/assets/pieces"
PIECE_SCALE = 0.70


class GameApplication:
    """
    Composition root that wires all game subsystems together.

    Does NOT contain game logic or rendering logic.
    """

    def __init__(self):
        self.engine = GameEngine(
            [row[:] for row in STARTING_BOARD]
        )

        self.renderer = Renderer(BOARD_IMAGE_PATH)
        self.sprite_manager = SpriteManager(PIECES_ROOT_PATH)

        self.rows = len(self.engine.board)
        self.cols = len(self.engine.board[0])

        cell_width, cell_height = self.renderer.get_cell_size(
            self.rows, self.cols
        )

        piece_size = (
            int(cell_width * PIECE_SCALE),
            int(cell_height * PIECE_SCALE),
        )

        self.graphics_manager = GraphicsManager(
            sprite_manager=self.sprite_manager,
            piece_size=piece_size,
        )

        self.synchronizer = GraphicsSynchronizer(
            self.graphics_manager,
            event_bus=self.engine.event_bus,
        )
        self.synchronizer.initialize(self.engine.board)

        board_mapper = BoardMapper(
            cell_width=cell_width,
            cell_height=cell_height,
        )

        self.controller = Controller(
            engine=self.engine,
            board_mapper=board_mapper,
        )

        self.mouse_input_adapter = MouseInputAdapter(
            self.controller,
            game_over_provider=lambda: self.engine.game_over,
        )

        self.frame_composer = FrameComposer(
            renderer=self.renderer,
            graphics_manager=self.graphics_manager,
            rows=self.rows,
            cols=self.cols,
            cooldown_provider=lambda: GraphicsSynchronizer.get_cooldown_indicators(
                self.engine.active_cooldowns,
                self.engine.clock,
                COOLDOWN_DURATION_MS,
            ),
            selection_provider=lambda: self.controller.selected,
            game_over_provider=lambda: self.engine.game_over,
        )

    def run(self):
        game_loop = GameLoop(
            frame_composer=self.frame_composer,
            graphics_manager=self.graphics_manager,
            synchronizer=self.synchronizer,
            pending_moves_provider=lambda: self.engine.pending_moves,
            board_provider=lambda: self.engine.board,
            active_jumps_provider=lambda: self.engine.active_jumps,
            engine_updater=lambda dt: self.engine.handle_wait(dt),
            mouse_input_adapter=self.mouse_input_adapter,
            target_fps=60,
        )
        game_loop.run()


if __name__ == "__main__":
    app = GameApplication()
    app.run()
