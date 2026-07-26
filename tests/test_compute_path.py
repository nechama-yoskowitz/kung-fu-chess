"""Unit tests for compute_path."""
import pytest
from game.realtime.motion import compute_path
from game.model.piece import (
    WHITE_ROOK, WHITE_BISHOP, WHITE_QUEEN, WHITE_KING, WHITE_PAWN, WHITE_KNIGHT,
    BLACK_QUEEN, BLACK_PAWN, BLACK_KNIGHT,
)


# ---------------------------------------------------------------------------
# Rook paths (straight lines)
# ---------------------------------------------------------------------------

def test_rook_horizontal_right():
    path = compute_path(WHITE_ROOK, 0, 0, 0, 4)
    assert path == [(0, 1), (0, 2), (0, 3), (0, 4)]


def test_rook_horizontal_left():
    path = compute_path(WHITE_ROOK, 0, 4, 0, 0)
    assert path == [(0, 3), (0, 2), (0, 1), (0, 0)]


def test_rook_vertical_down():
    path = compute_path(WHITE_ROOK, 0, 0, 4, 0)
    assert path == [(1, 0), (2, 0), (3, 0), (4, 0)]


def test_rook_vertical_up():
    path = compute_path(WHITE_ROOK, 4, 0, 0, 0)
    assert path == [(3, 0), (2, 0), (1, 0), (0, 0)]


def test_rook_one_step():
    path = compute_path(WHITE_ROOK, 0, 0, 0, 1)
    assert path == [(0, 1)]


# ---------------------------------------------------------------------------
# Bishop paths (diagonals)
# ---------------------------------------------------------------------------

def test_bishop_diagonal_down_right():
    path = compute_path(WHITE_BISHOP, 0, 0, 3, 3)
    assert path == [(1, 1), (2, 2), (3, 3)]


def test_bishop_diagonal_up_left():
    path = compute_path(WHITE_BISHOP, 3, 3, 0, 0)
    assert path == [(2, 2), (1, 1), (0, 0)]


def test_bishop_diagonal_one_step():
    path = compute_path(WHITE_BISHOP, 2, 2, 1, 3)
    assert path == [(1, 3)]


# ---------------------------------------------------------------------------
# Queen paths (straight or diagonal)
# ---------------------------------------------------------------------------

def test_queen_horizontal():
    path = compute_path(WHITE_QUEEN, 3, 0, 3, 5)
    assert path == [(3, 1), (3, 2), (3, 3), (3, 4), (3, 5)]


def test_queen_diagonal():
    path = compute_path(WHITE_QUEEN, 0, 0, 2, 2)
    assert path == [(1, 1), (2, 2)]


def test_queen_vertical():
    path = compute_path(BLACK_QUEEN, 0, 3, 4, 3)
    assert path == [(1, 3), (2, 3), (3, 3), (4, 3)]


# ---------------------------------------------------------------------------
# King paths (one step)
# ---------------------------------------------------------------------------

def test_king_one_step_diagonal():
    path = compute_path(WHITE_KING, 4, 4, 3, 5)
    assert path == [(3, 5)]


def test_king_one_step_horizontal():
    path = compute_path(WHITE_KING, 0, 0, 0, 1)
    assert path == [(0, 1)]


# ---------------------------------------------------------------------------
# Pawn paths
# ---------------------------------------------------------------------------

def test_pawn_one_step_forward():
    path = compute_path(WHITE_PAWN, 6, 0, 5, 0)
    assert path == [(5, 0)]


def test_pawn_two_step_forward():
    path = compute_path(WHITE_PAWN, 6, 0, 4, 0)
    assert path == [(5, 0), (4, 0)]


def test_pawn_diagonal_capture():
    path = compute_path(WHITE_PAWN, 6, 3, 5, 4)
    assert path == [(5, 4)]


def test_black_pawn_one_step():
    path = compute_path(BLACK_PAWN, 1, 0, 2, 0)
    assert path == [(2, 0)]


def test_black_pawn_two_step():
    path = compute_path(BLACK_PAWN, 1, 0, 3, 0)
    assert path == [(2, 0), (3, 0)]


# ---------------------------------------------------------------------------
# Knight paths (jump — no intermediates)
# ---------------------------------------------------------------------------

def test_knight_path_is_only_destination():
    path = compute_path(WHITE_KNIGHT, 4, 4, 2, 5)
    assert path == [(2, 5)]


def test_knight_path_other_direction():
    path = compute_path(WHITE_KNIGHT, 0, 0, 1, 2)
    assert path == [(1, 2)]


def test_knight_has_no_intermediate_cells():
    path = compute_path(BLACK_KNIGHT, 7, 1, 5, 2)
    assert len(path) == 1
    assert path[0] == (5, 2)
