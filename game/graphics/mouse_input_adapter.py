import cv2

from game.graphics.img import Img


class MouseInputAdapter:
    """
    Receives mouse events from the OpenCV window and delegates
    click actions to the Controller.

    Handles board offset translation: converts window-level pixel
    coordinates into board-local coordinates before forwarding
    to the Controller. Scales coordinates to the original board
    image size so the Controller's BoardMapper works correctly.
    """

    def __init__(self, controller, game_over_provider=None,
                 board_rect_provider=None, original_board_size_provider=None,
                 input_blocked_provider=None):
        self.controller = controller
        self.game_over_provider = game_over_provider
        # board_rect_provider returns (left, top, width, height) of the displayed board
        self.board_rect_provider = board_rect_provider
        # original_board_size_provider returns (width, height) of the original board image
        self.original_board_size_provider = original_board_size_provider
        # input_blocked_provider returns True when gameplay input should be ignored
        # (e.g. during game-start countdown)
        self.input_blocked_provider = input_blocked_provider

    def register(self, window_name: str) -> None:
        """Register the mouse callback on the given OpenCV window."""
        Img.set_mouse_callback(window_name, self._on_mouse_event)

    def _on_mouse_event(self, event, x, y, flags, param) -> None:
        """OpenCV mouse callback handler."""
        if self.game_over_provider and self.game_over_provider():
            return

        if self.input_blocked_provider and self.input_blocked_provider():
            return

        if event not in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_RBUTTONDOWN):
            return

        # Translate window coords to board-local coords
        local_x, local_y = self._to_board_local(x, y)
        if local_x is None:
            return  # Click was outside the board

        if event == cv2.EVENT_LBUTTONDOWN:
            self.controller.click(local_x, local_y)
        elif event == cv2.EVENT_RBUTTONDOWN:
            self.controller.jump(local_x, local_y)

    def _to_board_local(self, x: int, y: int):
        """
        Convert window coordinates to original-board-image coordinates.

        Returns (scaled_x, scaled_y) or (None, None) if outside the board.
        """
        if not self.board_rect_provider:
            return x, y

        board_left, board_top, board_width, board_height = self.board_rect_provider()

        local_x = x - board_left
        local_y = y - board_top

        if local_x < 0 or local_y < 0:
            return None, None
        if local_x >= board_width or local_y >= board_height:
            return None, None

        # Scale to original board image size if available
        if self.original_board_size_provider:
            orig_w, orig_h = self.original_board_size_provider()
            if board_width > 0 and board_height > 0:
                local_x = int(local_x * orig_w / board_width)
                local_y = int(local_y * orig_h / board_height)

        return local_x, local_y
