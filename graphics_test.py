from game.controller.controller import Controller
from game.engine.game_engine import GameEngine
from game.graphics.game_loop import GameLoop
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.graphics_synchronizer import GraphicsSynchronizer
from game.graphics.mouse_input_adapter import MouseInputAdapter
from game.graphics.renderer import Renderer
from game.graphics.sprite_manager import SpriteManager
from game.model.board_mapper import BoardMapper
from game.model.constants import COOLDOWN_DURATION_MS


# --- Game engine setup ---

board = [
    ["bR", "bN", "bB", "bQ", "bK", "bB", "bN", "bR"],
    ["bP", "bP", "bP", "bP", "bP", "bP", "bP", "bP"],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    ["wP", "wP", "wP", "wP", "wP", "wP", "wP", "wP"],
    ["wR", "wN", "wB", "wQ", "wK", "wB", "wN", "wR"],
]

engine = GameEngine(board)

# --- Graphics setup ---

renderer = Renderer("game/graphics/assets/board.png")

sprite_manager = SpriteManager("game/graphics/assets/pieces")

rows = len(engine.board)
cols = len(engine.board[0])

cell_width, cell_height = renderer.get_cell_size(rows, cols)

piece_size = (
    int(cell_width * 0.70),
    int(cell_height * 0.70),
)

graphics_manager = GraphicsManager(
    sprite_manager=sprite_manager,
    piece_size=piece_size,
)

# --- Synchronize graphics from engine state ---

synchronizer = GraphicsSynchronizer(graphics_manager)
synchronizer.initialize(engine.board)

# --- Controller with correctly-sized BoardMapper ---

board_mapper = BoardMapper(
    cell_width=cell_width,
    cell_height=cell_height,
)

controller = Controller(
    engine=engine,
    board_mapper=board_mapper,
)

# --- Mouse input adapter ---

mouse_input_adapter = MouseInputAdapter(
    controller,
    game_over_provider=lambda: engine.game_over,
)

# --- Run the game loop (interactive) ---

game_loop = GameLoop(
    renderer=renderer,
    graphics_manager=graphics_manager,
    rows=rows,
    cols=cols,
    synchronizer=synchronizer,
    pending_moves_provider=lambda: engine.pending_moves,
    board_provider=lambda: engine.board,
    engine_updater=lambda dt: engine.handle_wait(dt),
    cooldown_provider=lambda: GraphicsSynchronizer.get_cooldown_indicators(
        engine.arbiter.active_cooldowns, engine.clock, COOLDOWN_DURATION_MS
    ),
    game_over_provider=lambda: engine.game_over,
    mouse_input_adapter=mouse_input_adapter,
    selection_provider=lambda: controller.selected,
    target_fps=60,
)

game_loop.run()
