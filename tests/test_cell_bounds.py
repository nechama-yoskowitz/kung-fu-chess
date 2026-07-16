"""
Tests for Renderer.get_cell_bounds — exact pixel boundary calculation.

Verifies that cell boundaries are consistent, gap-free, and cover the
full board dimensions regardless of divisibility.
"""

from unittest.mock import MagicMock

import numpy as np

from game.graphics.renderer import Renderer


def _make_renderer(width, height):
    """Create a Renderer with a mock board template of given dimensions."""
    renderer = Renderer.__new__(Renderer)
    renderer.board_template = MagicMock()
    renderer.board_template.img = MagicMock()
    renderer.board_template.img.shape = (height, width, 3)
    renderer.board_template.img.copy = MagicMock(
        return_value=np.zeros((height, width, 3), dtype=np.uint8)
    )
    renderer.canvas = None
    return renderer


class TestCellBoundsFirstRowCol:
    """First row/column starts at pixel 0."""

    def test_first_cell_starts_at_zero(self):
        renderer = _make_renderer(822, 828)
        left, top, right, bottom = renderer.get_cell_bounds(0, 0, 8, 8)
        assert left == 0
        assert top == 0

    def test_first_cell_has_positive_size(self):
        renderer = _make_renderer(822, 828)
        left, top, right, bottom = renderer.get_cell_bounds(0, 0, 8, 8)
        assert right > left
        assert bottom > top


class TestCellBoundsMiddleCells:
    """Middle cells have consistent boundaries."""

    def test_middle_cell_bounds(self):
        renderer = _make_renderer(822, 828)
        left, top, right, bottom = renderer.get_cell_bounds(3, 4, 8, 8)
        assert left > 0
        assert top > 0
        assert right > left
        assert bottom > top

    def test_middle_cell_width_reasonable(self):
        renderer = _make_renderer(822, 828)
        left, top, right, bottom = renderer.get_cell_bounds(3, 4, 8, 8)
        width = right - left
        height = bottom - top
        # Should be approximately 822/8 ≈ 102-103
        assert 102 <= width <= 103
        assert 103 <= height <= 104


class TestCellBoundsLastRowCol:
    """Last row/column ends at the board edge."""

    def test_last_cell_ends_at_board_width(self):
        renderer = _make_renderer(822, 828)
        left, top, right, bottom = renderer.get_cell_bounds(7, 7, 8, 8)
        assert right == 822
        assert bottom == 828

    def test_last_cell_starts_correctly(self):
        renderer = _make_renderer(822, 828)
        left, top, right, bottom = renderer.get_cell_bounds(7, 7, 8, 8)
        assert left > 0
        assert top > 0
        width = right - left
        height = bottom - top
        assert 102 <= width <= 103
        assert 103 <= height <= 104


class TestAdjacentCellsShareBorders:
    """Adjacent cells share the exact same border pixel."""

    def test_horizontal_adjacency(self):
        renderer = _make_renderer(822, 828)
        for col in range(7):
            _, _, right1, _ = renderer.get_cell_bounds(0, col, 8, 8)
            left2, _, _, _ = renderer.get_cell_bounds(0, col + 1, 8, 8)
            assert right1 == left2, f"Gap/overlap between col {col} and {col+1}"

    def test_vertical_adjacency(self):
        renderer = _make_renderer(822, 828)
        for row in range(7):
            _, _, _, bottom1 = renderer.get_cell_bounds(row, 0, 8, 8)
            _, top2, _, _ = renderer.get_cell_bounds(row + 1, 0, 8, 8)
            assert bottom1 == top2, f"Gap/overlap between row {row} and {row+1}"


class TestFullBoardCoverage:
    """All cells together exactly cover the board with no lost pixels."""

    def test_total_width_coverage_822x828(self):
        renderer = _make_renderer(822, 828)
        total_width = 0
        for col in range(8):
            left, _, right, _ = renderer.get_cell_bounds(0, col, 8, 8)
            total_width += (right - left)
        assert total_width == 822

    def test_total_height_coverage_822x828(self):
        renderer = _make_renderer(822, 828)
        total_height = 0
        for row in range(8):
            _, top, _, bottom = renderer.get_cell_bounds(row, 0, 8, 8)
            total_height += (bottom - top)
        assert total_height == 828

    def test_first_cell_left_is_zero_last_cell_right_is_width(self):
        renderer = _make_renderer(822, 828)
        left0, _, _, _ = renderer.get_cell_bounds(0, 0, 8, 8)
        _, _, right7, _ = renderer.get_cell_bounds(0, 7, 8, 8)
        assert left0 == 0
        assert right7 == 822

    def test_first_cell_top_is_zero_last_cell_bottom_is_height(self):
        renderer = _make_renderer(822, 828)
        _, top0, _, _ = renderer.get_cell_bounds(0, 0, 8, 8)
        _, _, _, bottom7 = renderer.get_cell_bounds(7, 0, 8, 8)
        assert top0 == 0
        assert bottom7 == 828


class TestNonStandard822x828:
    """Verify with the exact board dimensions used in the project."""

    def test_all_cells_exact_coverage(self):
        renderer = _make_renderer(822, 828)
        for row in range(8):
            for col in range(8):
                left, top, right, bottom = renderer.get_cell_bounds(row, col, 8, 8)
                assert right > left
                assert bottom > top
                # Verify no boundary exceeds board
                assert left >= 0
                assert top >= 0
                assert right <= 822
                assert bottom <= 828

    def test_no_gaps_full_grid(self):
        """Every pixel column is covered by exactly one cell."""
        renderer = _make_renderer(822, 828)
        covered_cols = set()
        for col in range(8):
            left, _, right, _ = renderer.get_cell_bounds(0, col, 8, 8)
            for px in range(left, right):
                assert px not in covered_cols, f"Pixel column {px} covered twice"
                covered_cols.add(px)
        assert len(covered_cols) == 822

    def test_no_gaps_full_grid_rows(self):
        """Every pixel row is covered by exactly one cell."""
        renderer = _make_renderer(822, 828)
        covered_rows = set()
        for row in range(8):
            _, top, _, bottom = renderer.get_cell_bounds(row, 0, 8, 8)
            for px in range(top, bottom):
                assert px not in covered_rows, f"Pixel row {px} covered twice"
                covered_rows.add(px)
        assert len(covered_rows) == 828
