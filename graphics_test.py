from game.graphics.sprite_loader import SpriteLoader


loader = SpriteLoader(
    "game/graphics/assets/pieces"
)

animation = loader.load_animation(
    piece="wQ",
    state="jump",
    size=(100, 100),
)

print("Number of frames:", len(animation.frames))
print("FPS:", animation.frames_per_sec)
print("Is loop:", animation.is_loop)
print("First frame type:", type(animation.frames[0]))