from game.model.constants import CELL_SIZE


class BoardMapper:
    """Convert pixel coordinates into board coordinates."""

    def __init__(self, cell_width: int = CELL_SIZE, cell_height: int = CELL_SIZE):
        self.cell_width = cell_width
        self.cell_height = cell_height

    def pixel_to_cell(self, x, y):
        row = int(y // self.cell_height)
        col = int(x // self.cell_width)
        return row, col
