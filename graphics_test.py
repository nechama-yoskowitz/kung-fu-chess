from game.graphics.graphic_piece import GraphicPiece
from game.graphics.piece_state_machine import PieceStateMachine
from game.graphics.sprite_manager import SpriteManager


sprite_manager = SpriteManager(
    "game/graphics/assets/pieces"
)

piece = GraphicPiece(
    piece="wQ",
    row=7,
    col=3,
    sprite_manager=sprite_manager,
    piece_size=(90, 90),
)

print("Initial state:", piece.state)

piece.set_state(PieceStateMachine.JUMP)
print("After jump request:", piece.state)

for _ in range(20):
    piece.update(125)

print("After jump animation:", piece.state)

piece.set_state(PieceStateMachine.MOVE)
print("After move request:", piece.state)

for _ in range(20):
    piece.update(125)

print("After move animation:", piece.state)