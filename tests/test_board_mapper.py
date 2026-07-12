import pytest
from game.input.board_mapper import BoardMapper


@pytest.fixture
def mapper():
    return BoardMapper()


# ---------------------------------------------------------------------------
# x controls column
# ---------------------------------------------------------------------------

def test_x_0_to_99_maps_to_column_0(mapper):
    _, col = mapper.pixel_to_cell(0, 0)
    assert col == 0
    _, col = mapper.pixel_to_cell(99, 0)
    assert col == 0


def test_x_100_to_199_maps_to_column_1(mapper):
    _, col = mapper.pixel_to_cell(100, 0)
    assert col == 1
    _, col = mapper.pixel_to_cell(199, 0)
    assert col == 1


def test_x_200_maps_to_column_2(mapper):
    _, col = mapper.pixel_to_cell(200, 0)
    assert col == 2


# ---------------------------------------------------------------------------
# y controls row
# ---------------------------------------------------------------------------

def test_y_0_to_99_maps_to_row_0(mapper):
    row, _ = mapper.pixel_to_cell(0, 0)
    assert row == 0
    row, _ = mapper.pixel_to_cell(0, 99)
    assert row == 0


def test_y_100_to_199_maps_to_row_1(mapper):
    row, _ = mapper.pixel_to_cell(0, 100)
    assert row == 1
    row, _ = mapper.pixel_to_cell(0, 199)
    assert row == 1


def test_y_200_maps_to_row_2(mapper):
    row, _ = mapper.pixel_to_cell(0, 200)
    assert row == 2


# ---------------------------------------------------------------------------
# x is column, y is row (not swapped)
# ---------------------------------------------------------------------------

def test_x_controls_column_and_y_controls_row(mapper):
    row, col = mapper.pixel_to_cell(150, 250)
    assert row == 2   # y=250 → row 2
    assert col == 1   # x=150 → col 1


# ---------------------------------------------------------------------------
# boundary values
# ---------------------------------------------------------------------------

def test_boundary_99(mapper):
    row, col = mapper.pixel_to_cell(99, 99)
    assert row == 0
    assert col == 0


def test_boundary_100(mapper):
    row, col = mapper.pixel_to_cell(100, 100)
    assert row == 1
    assert col == 1


def test_boundary_199(mapper):
    row, col = mapper.pixel_to_cell(199, 199)
    assert row == 1
    assert col == 1


def test_boundary_200(mapper):
    row, col = mapper.pixel_to_cell(200, 200)
    assert row == 2
    assert col == 2
