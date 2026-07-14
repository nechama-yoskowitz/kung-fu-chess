from dataclasses import dataclass

from game.graphics.img import Img


@dataclass
class AnimationData:
    frames: list[Img]
    frames_per_sec: int
    is_loop: bool