"""
Full-window layout composer with side panels, board placement, and score display.

Layout:
+----------------+--------------------------+----------------+
| BLACK          |                          | WHITE          |
| Score: X       |          BOARD           | Score: Y       |
|                |                          |                |
| Time | Move    |                          | Time | Move    |
+----------------+--------------------------+----------------+
"""

import cv2
import numpy as np

from game.graphics.frame_composer import FrameComposer
from game.graphics.img import Img


# Layout constants
PANEL_WIDTH_RATIO = 0.18  # Each panel takes 18% of window width
MIN_BOARD_SIZE = 200
PANEL_BG_COLOR = (40, 40, 40)  # Dark gray
SCREEN_BG_COLOR = (30, 30, 30)  # Darker gray
PANEL_BORDER_COLOR = (80, 80, 80)
TEXT_COLOR = (220, 220, 220)
HEADER_COLOR = (255, 255, 255)
SCORE_COLOR = (0, 200, 255)  # Orange-yellow


class LayoutMetrics:
    """Computed layout positions for the current window size."""

    def __init__(self, window_width, window_height):
        self.window_width = window_width
        self.window_height = window_height

        panel_width = max(120, int(window_width * PANEL_WIDTH_RATIO))
        self.panel_width = panel_width

        # Board area is between the two panels
        available_width = window_width - 2 * panel_width
        available_height = window_height

        # Board must be square and fit in the available area
        board_size = max(MIN_BOARD_SIZE, min(available_width, available_height))
        self.board_size = board_size

        # Center the board vertically and horizontally in its area
        self.board_left = panel_width + (available_width - board_size) // 2
        self.board_top = (window_height - board_size) // 2
        self.board_right = self.board_left + board_size
        self.board_bottom = self.board_top + board_size

        self.left_panel_x = 0
        self.right_panel_x = window_width - panel_width


class GameScreenComposer:
    """
    Composes the full game window: panels + board + overlays.

    Owns the full-window canvas and delegates board rendering to FrameComposer.
    """

    def __init__(
        self,
        frame_composer: FrameComposer,
        window_width: int = 1200,
        window_height: int = 800,
        white_score_provider=None,
        black_score_provider=None,
        white_moves_provider=None,
        black_moves_provider=None,
    ):
        self.frame_composer = frame_composer
        self.window_width = window_width
        self.window_height = window_height
        self.white_score_provider = white_score_provider
        self.black_score_provider = black_score_provider
        self.white_moves_provider = white_moves_provider
        self.black_moves_provider = black_moves_provider
        self._metrics = LayoutMetrics(window_width, window_height)

    @property
    def metrics(self) -> LayoutMetrics:
        return self._metrics

    def update_window_size(self, width: int, height: int) -> None:
        """Recompute layout when window is resized."""
        if width != self.window_width or height != self.window_height:
            self.window_width = width
            self.window_height = height
            self._metrics = LayoutMetrics(width, height)

    def compose(self) -> Img:
        """Compose the full game screen and return it as an Img."""
        m = self._metrics

        # Create full-window canvas (BGR)
        screen = Img()
        screen.img = np.full(
            (m.window_height, m.window_width, 3),
            SCREEN_BG_COLOR, dtype=np.uint8
        )

        # Draw side panels
        self._draw_panel(screen, m.left_panel_x, m.panel_width, m.window_height, "BLACK",
                         self.black_score_provider, self.black_moves_provider)
        self._draw_panel(screen, m.right_panel_x, m.panel_width, m.window_height, "WHITE",
                         self.white_score_provider, self.white_moves_provider)

        # Render the board via FrameComposer
        board_canvas = self.frame_composer.compose()

        # Resize board to fit the layout
        board_img = cv2.resize(
            board_canvas.img, (m.board_size, m.board_size),
            interpolation=cv2.INTER_AREA
        )

        # Ensure channel count matches
        if board_img.shape[2] == 4 and screen.img.shape[2] == 3:
            board_img = cv2.cvtColor(board_img, cv2.COLOR_BGRA2BGR)

        # Place board on the screen canvas
        screen.img[m.board_top:m.board_bottom, m.board_left:m.board_right] = board_img

        return screen

    def _draw_panel(self, screen: Img, x: int, width: int, height: int,
                    title: str, score_provider, moves_provider):
        """Draw a side panel with title, score, and move table."""
        # Panel background
        screen.fill_rectangle(x, 0, width, height, color=PANEL_BG_COLOR)

        # Panel border (right edge for left panel, left edge for right panel)
        if x == 0:
            border_x = x + width - 1
        else:
            border_x = x
        cv2.line(screen.img, (border_x, 0), (border_x, height - 1),
                 PANEL_BORDER_COLOR, 1)

        # Title
        pad = 12
        y_cursor = 30
        cv2.putText(screen.img, title, (x + pad, y_cursor),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, HEADER_COLOR, 2, cv2.LINE_AA)

        # Score
        y_cursor += 35
        score = score_provider() if score_provider else 0
        cv2.putText(screen.img, f"Score: {score}", (x + pad, y_cursor),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, SCORE_COLOR, 1, cv2.LINE_AA)

        # Table header
        y_cursor += 35
        cv2.putText(screen.img, "Time", (x + pad, y_cursor),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, TEXT_COLOR, 1, cv2.LINE_AA)
        cv2.putText(screen.img, "Move", (x + pad + 65, y_cursor),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, TEXT_COLOR, 1, cv2.LINE_AA)

        # Separator line
        y_cursor += 8
        cv2.line(screen.img, (x + pad, y_cursor), (x + width - pad, y_cursor),
                 PANEL_BORDER_COLOR, 1)

        # Move rows
        y_cursor += 5
        moves = moves_provider() if moves_provider else []
        for move_entry in moves[:15]:  # Show last 15 moves max
            y_cursor += 18
            if y_cursor > height - 20:
                break
            time_str = move_entry.get("time", "")
            move_str = move_entry.get("move", "")
            cv2.putText(screen.img, time_str, (x + pad, y_cursor),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, TEXT_COLOR, 1, cv2.LINE_AA)
            cv2.putText(screen.img, move_str, (x + pad + 65, y_cursor),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, TEXT_COLOR, 1, cv2.LINE_AA)
