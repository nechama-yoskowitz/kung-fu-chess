from game.graphics.animation import Animation
from game.graphics.sprite_loader import SpriteLoader


loader = SpriteLoader(
    "game/graphics/assets/pieces"
)

data = loader.load_animation(
    piece="wQ",
    state="jump",
    size=(100, 100),
)

animation = Animation(data)

print("Start:", animation.current_frame_index)

animation.update(124)
print("After 124 ms:", animation.current_frame_index)

animation.update(1)
print("After 125 ms:", animation.current_frame_index)

animation.update(125)
print("After 250 ms:", animation.current_frame_index)

animation.update(1000)
print("Final index:", animation.current_frame_index)
print("Finished:", animation.is_finished())

animation.reset()
print("After reset:", animation.current_frame_index)
print("Finished after reset:", animation.is_finished())