from game.graphics.sprite_loader import SpriteLoader


loader = SpriteLoader(
    "game/graphics/assets/pieces"
)

frames = loader.load_state_frames(
    piece="wQ",
    state="jump",
    size=(100, 100),
)

print("Number of frames:", len(frames))
print("First frame type:", type(frames[0]))