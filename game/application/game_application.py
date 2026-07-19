"""
Composition root that wires all game subsystems together.
"""

from game.controller.controller import Controller
from game.controller.local_game_gateway import LocalGameGateway
from game.engine.game_engine import GameEngine
from game.events.engine_events import GameStarted
from game.graphics.frame_composer import FrameComposer
from game.graphics.game_end_animation import GameEndAnimation
from game.graphics.game_loop import GameLoop
from game.graphics.game_screen_composer import GameScreenComposer
from game.graphics.game_start_animation import GameStartAnimation
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.graphics_synchronizer import GraphicsSynchronizer
from game.graphics.mouse_input_adapter import MouseInputAdapter
from game.graphics.renderer import Renderer
from game.graphics.sprites.sprite_manager import SpriteManager
from game.history.move_history_observer import MoveHistoryObserver
from game.model.board_mapper import BoardMapper
from game.model.constants import COOLDOWN_DURATION_MS
from game.sound.sound_observer import SoundObserver
from game.sound.sound_player import SoundPlayer


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
SOUNDS_ROOT_PATH = "game/graphics/assets/sounds"
PIECE_SCALE = 0.70
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800


class GameApplication:
    """
    Composition root — creates and connects all subsystems.

    Does NOT contain game logic or rendering logic.
    """

    def __init__(self):
        self.engine = GameEngine(
            [row[:] for row in STARTING_BOARD]
        )

        self.renderer = Renderer(BOARD_IMAGE_PATH)
        self.sprite_manager = SpriteManager(PIECES_ROOT_PATH)

        self.move_history = MoveHistoryObserver(
            event_bus=self.engine.event_bus,
            clock_provider=lambda: self.engine.clock,
        )

        self.sound_player = SoundPlayer(SOUNDS_ROOT_PATH)
        self.sound_observer = SoundObserver(
            event_bus=self.engine.event_bus,
            sound_player=self.sound_player,
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

        self.gateway = LocalGameGateway(self.engine)

        self.controller = Controller(
            gateway=self.gateway,
            board_mapper=BoardMapper(
                cell_width=cell_width,
                cell_height=cell_height,
            ),
        )

        self.game_end_animation = GameEndAnimation(
            event_bus=self.engine.event_bus,
        )

        self.game_start_animation = GameStartAnimation(
            event_bus=self.engine.event_bus,
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
            game_end_animation=self.game_end_animation,
            game_start_animation=self.game_start_animation,
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
            input_blocked_provider=lambda: self.game_start_animation.active,
        )

    def _get_board_rect(self):
        m = self.screen_composer.metrics
        return (m.board_left, m.board_top, m.board_size, m.board_size)

    def _get_original_board_size(self):
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
            game_end_animation=self.game_end_animation,
            game_start_animation=self.game_start_animation,
            target_fps=60,
        )

        # Publish GameStarted after all subsystems are wired but before the loop runs.
        self.engine.event_bus.publish(GameStarted())

        game_loop.run()
