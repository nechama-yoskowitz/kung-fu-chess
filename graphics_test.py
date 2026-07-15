from game.engine.game_engine import GameEngine
from game.graphics.game_loop import GameLoop
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.graphics_synchronizer import GraphicsSynchronizer
from game.graphics.renderer import Renderer
from game.graphics.sprite_manager import SpriteManager


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

# --- Run the game loop ---

game_loop = GameLoop(
    renderer=renderer,
    graphics_manager=graphics_manager,
    rows=rows,
    cols=cols,
    target_fps=60,
)

game_loop.run()
