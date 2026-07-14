
from pathlib import Path

from game.graphics.img import Img
from game.graphics.sprite_mapper import piece_to_sprite_folder


class SpriteLoader:
    def __init__(self, pieces_root):
        self.pieces_root = Path(pieces_root)

    def load_state_frames(self, piece, state, size):
        folder_name = piece_to_sprite_folder(piece)

        sprites_folder = (
            self.pieces_root
            / folder_name
            / "states"
            / state
            / "sprites"
        )

        if not sprites_folder.exists():
            raise FileNotFoundError(
                f"Sprites folder not found: {sprites_folder}"
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

        return frames