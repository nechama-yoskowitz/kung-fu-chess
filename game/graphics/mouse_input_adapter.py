import cv2

from game.graphics.img import Img


class MouseInputAdapter:
    """
    Receives mouse events from the OpenCV window and delegates
    click actions to the Controller.

    Responsibilities:
    - Listen for left-button mouse clicks on the game window.
    - Forward raw pixel coordinates to controller.click(x, y).
    - Ignore gameplay clicks when game_over_provider returns True.
    - The Controller's BoardMapper handles pixel-to-cell conversion.
    - Does NOT contain chess rules or selection logic.
    """

    def __init__(self, controller, game_over_provider=None):
        self.controller = controller
        self.game_over_provider = game_over_provider

    def register(self, window_name: str) -> None:
        """Register the mouse callback on the given OpenCV window."""
        Img.set_mouse_callback(window_name, self._on_mouse_event)

    def _on_mouse_event(self, event, x, y, flags, param) -> None:
        """OpenCV mouse callback handler."""
        if event == cv2.EVENT_LBUTTONDOWN:
            if self.game_over_provider and self.game_over_provider():
                return
            self.controller.click(x, y)
