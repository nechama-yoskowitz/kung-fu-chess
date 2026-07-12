import pytest
from game.model.pieces import get_color, get_type, same_color


# ---------------------------------------------------------------------------
# get_color
# ---------------------------------------------------------------------------

def test_get_color_white_piece():
    assert get_color("wK") == "w"


def test_get_color_black_piece():
    assert get_color("bQ") == "b"


def test_get_color_empty_cell():
    assert get_color(".") is None


# ---------------------------------------------------------------------------
# get_type
# ---------------------------------------------------------------------------

def test_get_type_king():
    assert get_type("wK") == "K"


def test_get_type_pawn():
    assert get_type("bP") == "P"


def test_get_type_empty_cell():
    assert get_type(".") is None


# ---------------------------------------------------------------------------
# same_color
# ---------------------------------------------------------------------------

def test_same_color_both_white():
    assert same_color("wK", "wR") is True


def test_same_color_both_black():
    assert same_color("bQ", "bN") is True


def test_same_color_different_colors():
    assert same_color("wK", "bK") is False


def test_same_color_first_is_empty():
    assert same_color(".", "wK") is False


def test_same_color_second_is_empty():
    assert same_color("wK", ".") is False


def test_same_color_both_empty():
    assert same_color(".", ".") is False
