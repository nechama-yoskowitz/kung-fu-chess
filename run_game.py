"""
Kung-Fu Chess — interactive graphical launcher.

This is the application entry point. It wires together the engine,
controller, graphics, input, and UI layers, then runs the game loop.
"""

from game.controller.controller import Controller
from game.engine.game_engine import GameEngine
from game.graphics.frame_composer import FrameComposer
from game.graphics.game_loop import GameLoop
from game.graphics.game_screen_composer import GameScreenComposer
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.graphics_synchronizer import GraphicsSynchronizer
from game.graphics.mouse_input_adapter import MouseInputAdapter
from game.graphics.renderer import Renderer
from game.graphics.sprite_manager import SpriteManager
from game.model.board_mapper import BoardMapper
from game.model.constants import COOLDOWN_DURATION_MS
from game.model.move_history import MoveHistoryObserver


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
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800


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

        # Move history subscribes to MoveResolved events via the EventBus.
        self.move_history = MoveHistoryObserver(
            event_bus=self.engine.event_bus,
            clock_provider=lambda: self.engine.clock,
        )

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

        self.controller = Controller(
            engine=self.engine,
            board_mapper=BoardMapper(
                cell_width=cell_width,
                cell_height=cell_height,
            ),
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

        self.screen_composer = GameScreenComposer(
            frame_composer=self.frame_composer,
            window_width=WINDOW_WIDTH,
            window_height=WINDOW_HEIGHT,
            white_score_provider=lambda: self.engine.white_score,
            black_score_provider=lambda: self.engine.black_score,
            white_moves_provider=lambda: self.move_history.white_moves,
            black_moves_provider=lambda: self.move_history.black_moves,
        )

        self.mouse_input_adapter = MouseInputAdapter(
            self.controller,
            game_over_provider=lambda: self.engine.game_over,
            board_rect_provider=self._get_board_rect,
            original_board_size_provider=self._get_original_board_size,
        )

    def _get_board_rect(self):
        """Return (left, top, width, height) of the displayed board."""
        m = self.screen_composer.metrics
        return (m.board_left, m.board_top, m.board_size, m.board_size)

    def _get_original_board_size(self):
        """Return (width, height) of the original board image."""
        h, w = self.renderer.board_template.img.shape[:2]
        return (w, h)

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
            screen_composer=self.screen_composer,
            target_fps=60,
        )
        game_loop.run()


if __name__ == "__main__":
    app = GameApplication()
    app.run()
