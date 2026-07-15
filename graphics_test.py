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

# מעט קטן יותר מהתא, כדי שהכלי לא ייגע בגבולות.
piece_size = (
    int(cell_width * 0.85),
    int(cell_height * 0.85),
)

canvas = renderer.start_frame()

for row in range(rows):
    for col in range(cols):
        piece = board[row][col]

        if piece == ".":
            continue

        animation_data = sprite_manager.get_animation_data(
            piece=piece,
            state="idle",
            size=piece_size,
        )

        first_frame = animation_data.frames[0]

        renderer.draw_piece_in_cell(
            piece_img=first_frame,
            row=row,
            col=col,
            rows=rows,
            cols=cols,
        )

canvas.show()