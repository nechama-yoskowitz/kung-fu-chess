from game.graphics.animation.animation_data import AnimationData
from game.graphics.sprites.sprite_loader import SpriteLoader


class SpriteManager:
    def __init__(self, pieces_root):
        self.loader = SpriteLoader(pieces_root)
        self._cache = {}

    def get_animation_data(
        self,
        piece: str,
        state: str,
        size: tuple[int, int],
    ) -> AnimationData:
        cache_key = (piece, state, size)

        if cache_key not in self._cache:
            self._cache[cache_key] = self.loader.load_animation(
                piece=piece,
                state=state,
                size=size,
            )

        return self._cache[cache_key]