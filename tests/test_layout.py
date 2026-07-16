"""
Tests for responsive layout, mouse coordinate transformation, and board sizing.
"""

import cv2
from unittest.mock import MagicMock

from game.graphics.game_screen_composer import LayoutMetrics, GameScreenComposer
from game.graphics.mouse_input_adapter import MouseInputAdapter


class TestLayoutMetricsBoardFit:
    """Board fits completely and remains square."""

    def test_board_is_square(self):
        m = LayoutMetrics(1200, 800)
        assert m.board_right - m.board_left == m.board_bottom - m.board_top

    def test_board_fits_in_small_window(self):
        m = LayoutMetrics(600, 400)
        assert m.board_size <= 400
        assert m.board_size <= (600 - 2 * m.panel_width)

    def test_board_fits_in_large_window(self):
        m = LayoutMetrics(1920, 1080)
        assert m.board_right <= 1920
        assert m.board_bottom <= 1080

    def test_board_within_window_bounds(self):
        for w, h in [(800, 600), (1200, 800), (1920, 1080), (640, 480)]:
            m = LayoutMetrics(w, h)
            assert m.board_left >= 0
            assert m.board_top >= 0
            assert m.board_right <= w
            assert m.board_bottom <= h


class TestLayoutMetricsCentering:
    """Board is centered between panels."""

    def test_board_horizontally_centered(self):
        m = LayoutMetrics(1200, 800)
        available_center = m.panel_width + (1200 - 2 * m.panel_width) / 2
        board_center = (m.board_left + m.board_right) / 2
        assert abs(available_center - board_center) <= 1

    def test_board_vertically_centered(self):
        m = LayoutMetrics(1200, 800)
        window_center = 800 / 2
        board_center = (m.board_top + m.board_bottom) / 2
        assert abs(window_center - board_center) <= 1


class TestLayoutMetricsPanelsVisible:
    """Side panels remain visible."""

    def test_panels_have_width(self):
        m = LayoutMetrics(1200, 800)
        assert m.panel_width >= 120

    def test_left_panel_at_zero(self):
        m = LayoutMetrics(1200, 800)
        assert m.left_panel_x == 0

    def test_right_panel_at_edge(self):
        m = LayoutMetrics(1200, 800)
        assert m.right_panel_x + m.panel_width == 1200


class TestLayoutMetricsMaximized:
    """Maximized window uses available space."""

    def test_maximized_board_grows(self):
        small = LayoutMetrics(800, 600)
        large = LayoutMetrics(1920, 1080)
        assert large.board_size > small.board_size

    def test_no_large_gray_area(self):
        m = LayoutMetrics(1200, 800)
        # Board should use most of the available height
        available = min(1200 - 2 * m.panel_width, 800)
        assert m.board_size >= available * 0.9


class TestMouseOutsideBoard:
    """Mouse clicks outside the board are ignored."""

    def test_click_in_left_panel_ignored(self):
        controller = MagicMock()
        controller.click = MagicMock()
        adapter = MouseInputAdapter(
            controller,
            board_rect_provider=lambda: (200, 50, 600, 600),
        )
        # Click in left panel at x=50
        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 50, 300, 0, None)
        controller.click.assert_not_called()

    def test_click_in_right_panel_ignored(self):
        controller = MagicMock()
        controller.click = MagicMock()
        adapter = MouseInputAdapter(
            controller,
            board_rect_provider=lambda: (200, 50, 600, 600),
        )
        # Click in right panel at x=900
        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 900, 300, 0, None)
        controller.click.assert_not_called()


class TestMouseTranslation:
    """Mouse clicks are translated correctly using board offset."""

    def test_top_left_cell(self):
        controller = MagicMock()
        controller.click = MagicMock()
        adapter = MouseInputAdapter(
            controller,
            board_rect_provider=lambda: (200, 50, 600, 600),
            original_board_size_provider=lambda: (822, 828),
        )
        # Click at the top-left of the board area
        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 200, 50, 0, None)
        controller.click.assert_called_once()
        args = controller.click.call_args[0]
        assert args[0] == 0  # x=0 in original coords
        assert args[1] == 0  # y=0 in original coords

    def test_center_cell(self):
        controller = MagicMock()
        controller.click = MagicMock()
        adapter = MouseInputAdapter(
            controller,
            board_rect_provider=lambda: (200, 50, 600, 600),
            original_board_size_provider=lambda: (600, 600),
        )
        # Click at the center of the displayed board
        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 500, 350, 0, None)
        controller.click.assert_called_once()
        args = controller.click.call_args[0]
        assert args[0] == 300  # center x
        assert args[1] == 300  # center y

    def test_bottom_right_cell(self):
        controller = MagicMock()
        controller.click = MagicMock()
        adapter = MouseInputAdapter(
            controller,
            board_rect_provider=lambda: (200, 50, 600, 600),
            original_board_size_provider=lambda: (822, 828),
        )
        # Click at the bottom-right of the displayed board (599, 599 from board origin)
        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 799, 649, 0, None)
        controller.click.assert_called_once()
        args = controller.click.call_args[0]
        # Should map to near the end of the original board
        assert args[0] > 700
        assert args[1] > 700

    def test_right_click_jump_works(self):
        controller = MagicMock()
        controller.jump = MagicMock()
        adapter = MouseInputAdapter(
            controller,
            board_rect_provider=lambda: (200, 50, 600, 600),
            original_board_size_provider=lambda: (600, 600),
        )
        adapter._on_mouse_event(cv2.EVENT_RBUTTONDOWN, 300, 200, 0, None)
        controller.jump.assert_called_once()
