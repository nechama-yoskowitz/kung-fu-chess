"""
Tests for mouse input, coordinate conversion, selection highlight,
and click delegation.
"""

import pytest
from unittest.mock import MagicMock, patch

from game.controller.board_mapper import BoardMapper
from game.controller.controller import Controller
from game.engine.game_engine import GameEngine
from game.graphics.mouse_input_adapter import MouseInputAdapter
from game.graphics.renderer import Renderer


# ─── BoardMapper coordinate conversion ───────────────────────────────────────


class TestBoardMapperConversion:
    """Test pixel-to-cell conversion with configurable cell dimensions."""

    def test_default_cell_size(self):
        mapper = BoardMapper()
        row, col = mapper.pixel_to_cell(150, 250)
        # default CELL_SIZE=100: x=150→col=1, y=250→row=2
        assert row == 2
        assert col == 1

    def test_custom_cell_size(self):
        mapper = BoardMapper(cell_width=80, cell_height=60)
        # x=160→col=2, y=120→row=2
        row, col = mapper.pixel_to_cell(160, 120)
        assert row == 2
        assert col == 2

    def test_origin_pixel(self):
        mapper = BoardMapper(cell_width=50, cell_height=50)
        row, col = mapper.pixel_to_cell(0, 0)
        assert row == 0
        assert col == 0

    def test_last_pixel_in_first_cell(self):
        mapper = BoardMapper(cell_width=100, cell_height=100)
        row, col = mapper.pixel_to_cell(99, 99)
        assert row == 0
        assert col == 0

    def test_first_pixel_in_second_cell(self):
        mapper = BoardMapper(cell_width=100, cell_height=100)
        row, col = mapper.pixel_to_cell(100, 100)
        assert row == 1
        assert col == 1

    def test_non_square_cells(self):
        mapper = BoardMapper(cell_width=120, cell_height=80)
        # x=240→col=2, y=160→row=2
        row, col = mapper.pixel_to_cell(240, 160)
        assert row == 2
        assert col == 2

    def test_pixel_at_boundary(self):
        mapper = BoardMapper(cell_width=75, cell_height=75)
        # x=75→col=1 (first pixel of second column)
        row, col = mapper.pixel_to_cell(75, 0)
        assert row == 0
        assert col == 1


# ─── Selection highlight cell bounds ─────────────────────────────────────────


class TestSelectionHighlight:
    """Test that draw_cell_highlight calculates correct cell bounds."""

    def _make_renderer_with_board(self, width, height):
        """Create a Renderer with a mock board template of given dimensions."""
        import numpy as np
        renderer = Renderer.__new__(Renderer)
        renderer.board_template = MagicMock()
        renderer.board_template.img = MagicMock()
        renderer.board_template.img.shape = (height, width, 3)
        renderer.board_template.img.copy = MagicMock(
            return_value=np.zeros((height, width, 3), dtype=np.uint8)
        )
        renderer.canvas = None
        return renderer

    def test_highlight_top_left_cell(self):
        renderer = self._make_renderer_with_board(800, 800)
        renderer.start_frame()

        with patch.object(renderer.canvas, 'draw_rectangle') as mock_rect:
            renderer.draw_cell_highlight(row=0, col=0, rows=8, cols=8)
            mock_rect.assert_called_once_with(
                x=0, y=0, width=100, height=100,
                color=(0, 255, 255), thickness=3,
            )

    def test_highlight_arbitrary_cell(self):
        renderer = self._make_renderer_with_board(800, 800)
        renderer.start_frame()

        with patch.object(renderer.canvas, 'draw_rectangle') as mock_rect:
            renderer.draw_cell_highlight(row=3, col=5, rows=8, cols=8)
            mock_rect.assert_called_once_with(
                x=500, y=300, width=100, height=100,
                color=(0, 255, 255), thickness=3,
            )

    def test_highlight_non_square_board(self):
        renderer = self._make_renderer_with_board(640, 480)
        renderer.start_frame()

        # 8 cols → cell_width=80, 6 rows → cell_height=80
        with patch.object(renderer.canvas, 'draw_rectangle') as mock_rect:
            renderer.draw_cell_highlight(row=2, col=3, rows=6, cols=8)
            mock_rect.assert_called_once_with(
                x=240, y=160, width=80, height=80,
                color=(0, 255, 255), thickness=3,
            )

    def test_highlight_outside_board_raises(self):
        renderer = self._make_renderer_with_board(800, 800)
        renderer.start_frame()

        with pytest.raises(ValueError):
            renderer.draw_cell_highlight(row=8, col=0, rows=8, cols=8)

    def test_highlight_without_start_frame_raises(self):
        renderer = self._make_renderer_with_board(800, 800)

        with pytest.raises(RuntimeError):
            renderer.draw_cell_highlight(row=0, col=0, rows=8, cols=8)


# ─── MouseInputAdapter click delegation ─────────────────────────────────────


class TestMouseInputAdapterDelegation:
    """Test that left clicks are delegated to the Controller exactly once."""

    def _make_board(self):
        return [
            ["bR", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wR", ".", ".", ".", ".", ".", ".", "."],
        ]

    def test_left_click_delegates_to_controller(self):
        import cv2
        engine = GameEngine(self._make_board())
        mapper = BoardMapper(cell_width=100, cell_height=100)
        controller = Controller(engine=engine, board_mapper=mapper)
        adapter = MouseInputAdapter(controller)

        controller.click = MagicMock(return_value=False)

        # Simulate left button down at (150, 750) → cell (7, 1)
        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 150, 750, 0, None)

        controller.click.assert_called_once_with(150, 750)

    def test_right_click_does_not_delegate(self):
        import cv2
        engine = GameEngine(self._make_board())
        mapper = BoardMapper(cell_width=100, cell_height=100)
        controller = Controller(engine=engine, board_mapper=mapper)
        adapter = MouseInputAdapter(controller)

        controller.click = MagicMock(return_value=False)

        adapter._on_mouse_event(cv2.EVENT_RBUTTONDOWN, 150, 750, 0, None)

        controller.click.assert_not_called()

    def test_mouse_move_does_not_delegate(self):
        import cv2
        engine = GameEngine(self._make_board())
        mapper = BoardMapper(cell_width=100, cell_height=100)
        controller = Controller(engine=engine, board_mapper=mapper)
        adapter = MouseInputAdapter(controller)

        controller.click = MagicMock(return_value=False)

        adapter._on_mouse_event(cv2.EVENT_MOUSEMOVE, 150, 750, 0, None)

        controller.click.assert_not_called()

    def test_click_selects_piece_via_controller(self):
        import cv2
        engine = GameEngine(self._make_board())
        mapper = BoardMapper(cell_width=100, cell_height=100)
        controller = Controller(engine=engine, board_mapper=mapper)
        adapter = MouseInputAdapter(controller)

        # Click on white rook at (7, 0): x=50, y=750
        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 50, 750, 0, None)

        assert controller.selected == (7, 0)

    def test_two_clicks_create_move(self):
        import cv2
        engine = GameEngine(self._make_board())
        mapper = BoardMapper(cell_width=100, cell_height=100)
        controller = Controller(engine=engine, board_mapper=mapper)
        adapter = MouseInputAdapter(controller)

        # First click: select white rook at (7, 0)
        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 50, 750, 0, None)
        assert controller.selected == (7, 0)

        # Second click: move to (0, 0) — valid rook move (straight up)
        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 50, 50, 0, None)
        assert controller.selected is None
        assert len(engine.pending_moves) == 1
        assert engine.pending_moves[0].to_row == 0
        assert engine.pending_moves[0].to_col == 0
