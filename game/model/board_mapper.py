from game.model.constants import CELL_SIZE


class BoardMapper:
    """Convert pixel coordinates into board coordinates."""

    def pixel_to_cell(self, x, y):
        row = y // CELL_SIZE
        col = x // CELL_SIZE
        return row, col