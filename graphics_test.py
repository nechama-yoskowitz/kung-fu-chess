from game.graphics.renderer import Renderer
from game.graphics.sprite_loader import SpriteLoader


renderer = Renderer(
    "game/graphics/assets/board.png"
)

loader = SpriteLoader(
    "game/graphics/assets/pieces"
)

animation_data = loader.load_animation(
    piece="wQ",
    state="jump",
    size=(100, 100),
)

canvas = renderer.start_frame()

first_frame = animation_data.frames[0]

renderer.draw_piece(
    piece_img=first_frame,
    x=50,
    y=50,
)

canvas.show()