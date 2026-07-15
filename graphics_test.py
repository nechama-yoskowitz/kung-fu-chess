from game.graphics.graphic_piece import GraphicPiece
from game.graphics.sprite_manager import SpriteManager


sprite_manager = SpriteManager(
    "game/graphics/assets/pieces"
)

graphic_piece = GraphicPiece(
    piece="wQ",
    row=7,
    col=3,
    sprite_manager=sprite_manager,
    piece_size=(90, 90),
)

print("Piece:", graphic_piece.piece)
print("Position:", graphic_piece.row, graphic_piece.col)
print("State:", graphic_piece.state)
print("Frame type:", type(graphic_piece.get_current_frame()))

graphic_piece.update(125)
print("Updated frame type:", type(graphic_piece.get_current_frame()))

graphic_piece.set_state("jump")
print("New state:", graphic_piece.state)

graphic_piece.set_position(6, 3)
print("New position:", graphic_piece.row, graphic_piece.col)