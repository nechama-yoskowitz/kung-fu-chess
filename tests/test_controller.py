import pytest
from game.input.controller import Controller


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeBoardMapper:
    """A controllable mapper for tests — returns a preset (row, col)."""

    def __init__(self, row=0, col=0):
        self._row = row
        self._col = col

    def set(self, row, col):
        self._row = row
        self._col = col

    def pixel_to_cell(self, x, y):
        return self._row, self._col


class FakeEngine:
    """
    A minimal fake GameEngine for Controller unit tests.

    All state is explicit and controllable without pulling in
    real rule validation or movement resolution.
    """

    def __init__(self, board):
        self.board = board
        self._moving_cells = set()
        self._move_accepted = True
        self._jump_accepted = True
        self.last_move_request = None
        self.last_jump_request = None

    def is_piece_moving_at(self, row, col):
        return (row, col) in self._moving_cells

    def request_move(self, from_row, from_col, to_row, to_col):
        self.last_move_request = (from_row, from_col, to_row, to_col)
        return self._move_accepted

    def request_jump(self, row, col):
        self.last_jump_request = (row, col)
        return self._jump_accepted


def make_board(rows):
    return [row.split() for row in rows]


# ---------------------------------------------------------------------------
# First click — selection
# ---------------------------------------------------------------------------

def test_first_click_on_piece_selects_it():
    board = make_board(["wR . ."])
    engine = FakeEngine(board)
    mapper = FakeBoardMapper(row=0, col=0)
    ctrl = Controller(engine, board_mapper=mapper)

    result = ctrl.click(0, 0)

    assert result is False
    assert ctrl.selected == (0, 0)


def test_first_click_on_empty_cell_leaves_selection_empty():
    board = make_board(["wR . ."])
    engine = FakeEngine(board)
    mapper = FakeBoardMapper(row=0, col=1)  # empty cell
    ctrl = Controller(engine, board_mapper=mapper)

    result = ctrl.click(100, 0)

    assert result is False
    assert ctrl.selected is None


def test_first_click_on_moving_piece_does_not_select():
    board = make_board(["wR . ."])
    engine = FakeEngine(board)
    engine._moving_cells.add((0, 0))
    mapper = FakeBoardMapper(row=0, col=0)
    ctrl = Controller(engine, board_mapper=mapper)

    result = ctrl.click(0, 0)

    assert result is False
    assert ctrl.selected is None


# ---------------------------------------------------------------------------
# Click outside the board
# ---------------------------------------------------------------------------

def test_click_outside_board_with_no_selection_does_nothing():
    board = make_board(["wR . ."])
    engine = FakeEngine(board)
    mapper = FakeBoardMapper(row=0, col=5)  # out of bounds for 3-col board
    ctrl = Controller(engine, board_mapper=mapper)

    result = ctrl.click(500, 0)

    assert result is False
    assert ctrl.selected is None


def test_click_outside_board_with_existing_selection_clears_it():
    board = make_board(["wR . ."])
    engine = FakeEngine(board)
    mapper = FakeBoardMapper(row=0, col=5)  # out of bounds
    ctrl = Controller(engine, board_mapper=mapper)
    ctrl.selected = (0, 0)

    result = ctrl.click(500, 0)

    assert result is False
    assert ctrl.selected is None


# ---------------------------------------------------------------------------
# Second click — move request
# ---------------------------------------------------------------------------

def test_second_click_calls_request_move_with_correct_coordinates():
    board = make_board(["wR . ."])
    engine = FakeEngine(board)
    engine._move_accepted = True
    mapper = FakeBoardMapper()
    ctrl = Controller(engine, board_mapper=mapper)

    # First click — select piece at (0, 0)
    ctrl.selected = (0, 0)

    # Second click — destination (0, 2)
    mapper.set(0, 2)
    result = ctrl.click(200, 0)

    assert result is True
    assert engine.last_move_request == (0, 0, 0, 2)


def test_second_click_clears_selection_when_move_accepted():
    board = make_board(["wR . ."])
    engine = FakeEngine(board)
    engine._move_accepted = True
    mapper = FakeBoardMapper(row=0, col=2)
    ctrl = Controller(engine, board_mapper=mapper)
    ctrl.selected = (0, 0)

    ctrl.click(200, 0)

    assert ctrl.selected is None


def test_second_click_clears_selection_when_move_rejected():
    board = make_board(["wR . ."])
    engine = FakeEngine(board)
    engine._move_accepted = False
    mapper = FakeBoardMapper(row=0, col=2)
    ctrl = Controller(engine, board_mapper=mapper)
    ctrl.selected = (0, 0)

    result = ctrl.click(200, 0)

    assert result is False
    assert ctrl.selected is None


# ---------------------------------------------------------------------------
# Friendly piece — switch selection
# ---------------------------------------------------------------------------

def test_clicking_friendly_non_moving_piece_switches_selection():
    board = make_board(["wR wB ."])
    engine = FakeEngine(board)
    mapper = FakeBoardMapper(row=0, col=1)
    ctrl = Controller(engine, board_mapper=mapper)
    ctrl.selected = (0, 0)

    result = ctrl.click(100, 0)

    assert result is False
    assert ctrl.selected == (0, 1)


def test_clicking_friendly_moving_piece_keeps_original_selection():
    board = make_board(["wR wB ."])
    engine = FakeEngine(board)
    engine._moving_cells.add((0, 1))
    mapper = FakeBoardMapper(row=0, col=1)
    ctrl = Controller(engine, board_mapper=mapper)
    ctrl.selected = (0, 0)

    result = ctrl.click(100, 0)

    assert result is False
    assert ctrl.selected == (0, 0)  # unchanged


# ---------------------------------------------------------------------------
# Jump
# ---------------------------------------------------------------------------

def test_jump_maps_pixel_and_calls_request_jump():
    board = make_board(["wR . ."])
    engine = FakeEngine(board)
    engine._jump_accepted = True
    mapper = FakeBoardMapper(row=0, col=0)
    ctrl = Controller(engine, board_mapper=mapper)

    result = ctrl.jump(50, 50)

    assert result is True
    assert engine.last_jump_request == (0, 0)


def test_jump_outside_board_returns_false():
    board = make_board(["wR . ."])
    engine = FakeEngine(board)
    mapper = FakeBoardMapper(row=0, col=5)  # out of bounds
    ctrl = Controller(engine, board_mapper=mapper)

    result = ctrl.jump(500, 0)

    assert result is False
    assert engine.last_jump_request is None


def test_jump_delegates_to_board_mapper():
    """Verify that the Controller uses its board_mapper, not hardcoded math."""
    board = make_board([". . .", ". . .", ". wR ."])
    engine = FakeEngine(board)
    engine._jump_accepted = True

    # Mapper always returns (2, 1) regardless of pixel input
    mapper = FakeBoardMapper(row=2, col=1)
    ctrl = Controller(engine, board_mapper=mapper)

    result = ctrl.jump(999, 999)  # arbitrary pixels

    assert result is True
    assert engine.last_jump_request == (2, 1)
