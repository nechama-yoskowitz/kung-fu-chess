from game.graphics.graphics_manager import GraphicsManager
from game.graphics.renderer import Renderer
from game.graphics.sprite_manager import SpriteManager


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


renderer = Renderer(
    "game/graphics/assets/board.png"
)

sprite_manager = SpriteManager(
    "game/graphics/assets/pieces"
)

rows = len(board)
cols = len(board[0])

cell_width, cell_height = renderer.get_cell_size(rows, cols)

piece_size = (
    int(cell_width * 0.85),
    int(cell_height * 0.85),
)

graphics_manager = GraphicsManager(
    sprite_manager=sprite_manager,
    piece_size=piece_size,
)

graphics_manager.initialize_from_board(board)

print("Graphic pieces:", len(graphics_manager.graphic_pieces))

graphics_manager.update(125)

canvas = renderer.start_frame()

graphics_manager.draw(
    renderer=renderer,
    rows=rows,
    cols=cols,
)

canvas.show()