import pytest
from game.rules import is_legal_move, is_legal_pawn_move, is_path_clear


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_board(rows):
    """Build a board from a list of space-separated strings."""
    return [row.split() for row in rows]


# ---------------------------------------------------------------------------
# is_legal_move — King
# ---------------------------------------------------------------------------

def test_king_move_one_step_horizontal():
    assert is_legal_move("wK", 4, 4, 4, 5) is True


def test_king_move_one_step_vertical():
    assert is_legal_move("wK", 4, 4, 5, 4) is True


def test_king_move_one_step_diagonal():
    assert is_legal_move("wK", 4, 4, 5, 5) is True


def test_king_move_two_steps_is_illegal():
    assert is_legal_move("wK", 4, 4, 4, 6) is False


def test_king_stay_in_place():
    # King "moving" to same square is geometrically allowed by is_legal_move
    # (though in practice the game logic would not create such a move)
    assert is_legal_move("wK", 4, 4, 4, 4) is True


# ---------------------------------------------------------------------------
# is_legal_move — Rook
# ---------------------------------------------------------------------------

def test_rook_move_along_row():
    assert is_legal_move("wR", 0, 0, 0, 7) is True


def test_rook_move_along_column():
    assert is_legal_move("wR", 0, 0, 7, 0) is True


def test_rook_move_diagonal_is_illegal():
    assert is_legal_move("wR", 0, 0, 3, 3) is False


# ---------------------------------------------------------------------------
# is_legal_move — Bishop
# ---------------------------------------------------------------------------

def test_bishop_move_diagonal():
    assert is_legal_move("wB", 0, 0, 3, 3) is True


def test_bishop_move_anti_diagonal():
    assert is_legal_move("wB", 4, 4, 2, 6) is True


def test_bishop_move_along_row_is_illegal():
    assert is_legal_move("wB", 0, 0, 0, 3) is False


def test_bishop_move_along_column_is_illegal():
    assert is_legal_move("wB", 0, 0, 3, 0) is False


# ---------------------------------------------------------------------------
# is_legal_move — Queen
# ---------------------------------------------------------------------------

def test_queen_move_along_row():
    assert is_legal_move("wQ", 3, 3, 3, 7) is True


def test_queen_move_along_column():
    assert is_legal_move("wQ", 3, 3, 7, 3) is True


def test_queen_move_diagonal():
    assert is_legal_move("wQ", 3, 3, 6, 6) is True


def test_queen_move_knight_pattern_is_illegal():
    assert is_legal_move("wQ", 3, 3, 5, 4) is False


# ---------------------------------------------------------------------------
# is_legal_move — Knight
# ---------------------------------------------------------------------------

def test_knight_move_two_one():
    assert is_legal_move("wN", 4, 4, 6, 5) is True


def test_knight_move_one_two():
    assert is_legal_move("wN", 4, 4, 5, 6) is True


def test_knight_move_backward():
    assert is_legal_move("wN", 4, 4, 2, 3) is True


def test_knight_move_straight_is_illegal():
    assert is_legal_move("wN", 4, 4, 4, 6) is False


def test_knight_move_diagonal_is_illegal():
    assert is_legal_move("wN", 4, 4, 6, 6) is False


# ---------------------------------------------------------------------------
# is_legal_pawn_move
# ---------------------------------------------------------------------------

def test_white_pawn_moves_forward_one():
    board = make_board([
        ". . .",
        "wP . .",
        ". . .",
    ])
    assert is_legal_pawn_move(board, "wP", 1, 0, 0, 0) is True


def test_black_pawn_moves_forward_one():
    board = make_board([
        ". . .",
        "bP . .",
        ". . .",
    ])
    assert is_legal_pawn_move(board, "bP", 1, 0, 2, 0) is True


def test_pawn_cannot_move_two_squares():
    board = make_board([
        ". . .",
        ". . .",
        "wP . .",
        ". . .",
    ])
    assert is_legal_pawn_move(board, "wP", 2, 0, 0, 0) is False


def test_pawn_forward_blocked_by_own_piece():
    board = make_board([
        "wR . .",
        "wP . .",
        ". . .",
    ])
    assert is_legal_pawn_move(board, "wP", 1, 0, 0, 0) is False


def test_pawn_forward_blocked_by_enemy_piece():
    board = make_board([
        "bR . .",
        "wP . .",
        ". . .",
    ])
    assert is_legal_pawn_move(board, "wP", 1, 0, 0, 0) is False


def test_white_pawn_captures_diagonally():
    board = make_board([
        ". bR .",
        "wP .  .",
        ". .  .",
    ])
    assert is_legal_pawn_move(board, "wP", 1, 0, 0, 1) is True


def test_black_pawn_captures_diagonally():
    board = make_board([
        ". .  .",
        "bP .  .",
        ". wR .",
    ])
    assert is_legal_pawn_move(board, "bP", 1, 0, 2, 1) is True


def test_pawn_cannot_capture_own_piece_diagonally():
    board = make_board([
        ". wR .",
        "wP .  .",
        ". .  .",
    ])
    assert is_legal_pawn_move(board, "wP", 1, 0, 0, 1) is False


def test_pawn_cannot_move_diagonally_to_empty_square():
    board = make_board([
        ". . .",
        "wP . .",
        ". . .",
    ])
    assert is_legal_pawn_move(board, "wP", 1, 0, 0, 1) is False


def test_white_pawn_cannot_move_backward():
    board = make_board([
        ". . .",
        "wP . .",
        ". . .",
    ])
    assert is_legal_pawn_move(board, "wP", 1, 0, 2, 0) is False


# ---------------------------------------------------------------------------
# is_path_clear
# ---------------------------------------------------------------------------

def test_path_clear_along_row():
    board = make_board([
        "wR . . . wK",
    ])
    assert is_path_clear(board, 0, 0, 0, 4) is True


def test_path_blocked_along_row():
    board = make_board([
        "wR . bP . wK",
    ])
    assert is_path_clear(board, 0, 0, 0, 4) is False


def test_path_clear_along_column():
    board = make_board([
        "wR",
        ".",
        ".",
        "wK",
    ])
    assert is_path_clear(board, 0, 0, 3, 0) is True


def test_path_blocked_along_column():
    board = make_board([
        "wR",
        "bP",
        ".",
        "wK",
    ])
    assert is_path_clear(board, 0, 0, 3, 0) is False


def test_path_clear_diagonal():
    board = make_board([
        "wB . . . .",
        ".  . . . .",
        ".  . . . .",
        ".  . . wK .",
    ])
    assert is_path_clear(board, 0, 0, 3, 3) is True


def test_path_blocked_diagonal():
    board = make_board([
        "wB . . . .",
        ".  bP . . .",
        ".  . . . .",
        ".  . . wK .",
    ])
    assert is_path_clear(board, 0, 0, 3, 3) is False


def test_path_clear_single_step():
    """Adjacent squares always have a clear path between them."""
    board = make_board([
        "wK wR",
    ])
    assert is_path_clear(board, 0, 0, 0, 1) is True
