import json
from pathlib import Path

from game.graphics.animation_data import AnimationData
from game.graphics.img import Img
from game.graphics.sprite_mapper import piece_to_sprite_folder

class SpriteLoader:
    def __init__(self, pieces_root):
        self.pieces_root = Path(pieces_root)

    def load_animation(self, piece, state, size):
        folder_name = piece_to_sprite_folder(piece)

        state_folder = (
            self.pieces_root
            / folder_name
            / "states"
            / state
        )

        sprites_folder = state_folder / "sprites"
        config_path = state_folder / "config.json"

        if not sprites_folder.exists():
            raise FileNotFoundError(
                f"Sprites folder not found: {sprites_folder}"
            )

        if not config_path.exists():
            raise FileNotFoundError(
                f"Animation config not found: {config_path}"
            )

        frame_paths = sorted(
            sprites_folder.glob("*.png"),
            key=lambda path: int(path.stem),
        )

        if not frame_paths:
            raise ValueError(
                f"No sprite frames found in: {sprites_folder}"
            )

        frames = []

        for frame_path in frame_paths:
            frame = Img().read(
                str(frame_path),
                size=size,
                keep_aspect=True,
            )
            frames.append(frame)

        with open(config_path, "r", encoding="utf-8") as file:
            config = json.load(file)

        graphics_config = config["graphics"]

        return AnimationData(
            frames=frames,
            frames_per_sec=graphics_config["frames_per_sec"],
            is_loop=graphics_config["is_loop"],
        )