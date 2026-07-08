import pytest
from io import StringIO
from unittest.mock import patch
from game.board import is_inside_board, validate_board, print_board, move_piece


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_board(rows):
    """Build a board from a list of space-separated strings."""
    return [row.split() for row in rows]


# ---------------------------------------------------------------------------
# is_inside_board
# ---------------------------------------------------------------------------

def test_inside_board_top_left_corner():
    board = make_board(["wK . .", ". . .", ". . ."])
    assert is_inside_board(board, 0, 0) is True


def test_inside_board_bottom_right_corner():
    board = make_board(["wK . .", ". . .", ". . ."])
    assert is_inside_board(board, 2, 2) is True


def test_inside_board_negative_row():
    board = make_board(["wK . .", ". . .", ". . ."])
    assert is_inside_board(board, -1, 0) is False


def test_inside_board_negative_col():
    board = make_board(["wK . .", ". . .", ". . ."])
    assert is_inside_board(board, 0, -1) is False


def test_inside_board_row_too_large():
    board = make_board(["wK . .", ". . .", ". . ."])
    assert is_inside_board(board, 3, 0) is False


def test_inside_board_col_too_large():
    board = make_board(["wK . .", ". . .", ". . ."])
    assert is_inside_board(board, 0, 3) is False


# ---------------------------------------------------------------------------
# validate_board
# ---------------------------------------------------------------------------

def test_validate_board_all_empty():
    board = make_board([". . .", ". . .", ". . ."])
    assert validate_board(board) is True


def test_validate_board_with_valid_pieces():
    board = make_board(["wK wQ wR", "wB wN wP", "bK bQ bR"])
    assert validate_board(board) is True


def test_validate_board_unknown_token(capsys):
    board = make_board(["wK wX .", ". . .", ". . ."])
    result = validate_board(board)
    assert result is False
    assert "ERROR UNKNOWN_TOKEN" in capsys.readouterr().out


def test_validate_board_row_width_mismatch(capsys):
    board = [["wK", ".", "."], [".", "."]]
    result = validate_board(board)
    assert result is False
    assert "ERROR ROW_WIDTH_MISMATCH" in capsys.readouterr().out


def test_validate_board_single_row():
    board = make_board(["wK bK ."])
    assert validate_board(board) is True


def test_validate_board_empty_board():
    board = []
    assert validate_board(board) is True


# ---------------------------------------------------------------------------
# move_piece
# ---------------------------------------------------------------------------

def test_move_piece_to_empty_square():
    board = make_board(["wK . .", ". . .", ". . ."])
    move_piece(board, 0, 0, 0, 2)
    assert board[0][2] == "wK"
    assert board[0][0] == "."


def test_move_piece_captures_enemy():
    board = make_board(["wK . bR", ". . .", ". . ."])
    move_piece(board, 0, 0, 0, 2)
    assert board[0][2] == "wK"
    assert board[0][0] == "."


def test_move_piece_source_becomes_empty():
    board = make_board(["wR . .", ". . .", ". . ."])
    move_piece(board, 0, 0, 2, 2)
    assert board[0][0] == "."


def test_move_piece_vertical():
    board = make_board(["wR", ".", "."])
    move_piece(board, 0, 0, 2, 0)
    assert board[2][0] == "wR"
    assert board[0][0] == "."
