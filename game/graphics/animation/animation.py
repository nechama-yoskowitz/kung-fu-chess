from game.graphics.animation.animation_data import AnimationData
from game.graphics.img import Img


class Animation:
    def __init__(self, data: AnimationData):
        if not data.frames:
            raise ValueError("Animation must contain at least one frame")

        if data.frames_per_sec <= 0:
            raise ValueError("frames_per_sec must be greater than zero")

        self.data = data
        self.current_frame_index = 0
        self.elapsed_time_ms = 0.0
        self.finished = False

    def update(self, delta_time_ms: float) -> None:
        if delta_time_ms < 0:
            raise ValueError("delta_time_ms cannot be negative")

        if self.finished:
            return

        self.elapsed_time_ms += delta_time_ms

        frame_duration_ms = 1000 / self.data.frames_per_sec

        while self.elapsed_time_ms >= frame_duration_ms:
            self.elapsed_time_ms -= frame_duration_ms
            self._advance_frame()

            if self.finished:
                break

    def _advance_frame(self) -> None:
        next_index = self.current_frame_index + 1

        if next_index < len(self.data.frames):
            self.current_frame_index = next_index
            return

        if self.data.is_loop:
            self.current_frame_index = 0
        else:
            self.current_frame_index = len(self.data.frames) - 1
            self.finished = True

    def get_current_frame(self) -> Img:
        return self.data.frames[self.current_frame_index]

    def reset(self) -> None:
        self.current_frame_index = 0
        self.elapsed_time_ms = 0.0
        self.finished = False

    def is_finished(self) -> bool:
        return self.finished