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
    # wP at row=1 on a 4-row board. Starting row for white is row=2.
    # row=1 is NOT the starting row, so two-square move is illegal.
    board = make_board([
        ". . .",
        "wP . .",
        ". . .",
        ". . .",
    ])
    assert is_legal_pawn_move(board, "wP", 1, 0, 3, 0) is False


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


# ---------------------------------------------------------------------------
# is_legal_move — unknown piece type
# (added after MOVEMENT_RULES dict replaced the if-chain in iteration 6:
#  the dict returns None for unknown types, which must produce False)
# ---------------------------------------------------------------------------

def test_unknown_piece_type_is_illegal():
    # "wX" has no entry in MOVEMENT_RULES — must return False, not crash
    assert is_legal_move("wX", 0, 0, 1, 1) is False


# ---------------------------------------------------------------------------
# _sign via is_path_clear — zero step (same row AND same col would be a
# no-op move, but _sign(0) must return 0 without crashing)
# (added to cover the _sign(0) branch introduced when we extracted _sign
#  as a named helper instead of inline ternaries)
# ---------------------------------------------------------------------------

def test_path_clear_same_row_step_is_zero():
    # Moving along a row: row_step == 0, col_step != 0.
    # _sign(0) is exercised for the row direction.
    board = make_board(["wR . . wK"])
    assert is_path_clear(board, 0, 0, 0, 3) is True


def test_path_clear_same_col_step_is_zero():
    # Moving along a column: col_step == 0, row_step != 0.
    # _sign(0) is exercised for the column direction.
    board = make_board(["wR", ".", ".", "wK"])
    assert is_path_clear(board, 0, 0, 3, 0) is True


# ===========================================================================
# Iteration 10 — pawn double step and promotion
# ===========================================================================

# ---------------------------------------------------------------------------
# pawn double step
# ---------------------------------------------------------------------------

def test_white_pawn_double_step_from_starting_row():
    # 8-row board. White starting row = row 7. wP moves 2 squares to row 5.
    board = make_board([
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        "wP . .",
    ])
    assert is_legal_pawn_move(board, "wP", 7, 0, 5, 0) is True


def test_black_pawn_double_step_from_starting_row():
    # 8-row board. Black starting row = row 0. bP moves 2 squares to row 2.
    board = make_board([
        "bP . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
    ])
    assert is_legal_pawn_move(board, "bP", 0, 0, 2, 0) is True


def test_pawn_cannot_double_step_from_non_starting_row():
    # wP at row=5 on 8-row board. Starting row is 7 → double step illegal.
    board = make_board([
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        "wP . .",
        ". . .",
        ". . .",
    ])
    assert is_legal_pawn_move(board, "wP", 5, 0, 3, 0) is False


def test_pawn_cannot_double_step_if_path_blocked():
    # Piece on row 6 blocks white pawn at row 7 from reaching row 5.
    board = make_board([
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        "bP . .",
        "wP . .",
    ])
    assert is_legal_pawn_move(board, "wP", 7, 0, 5, 0) is False


def test_pawn_cannot_double_step_if_destination_occupied():
    # Piece on row 5 blocks white pawn at row 7 from landing there.
    board = make_board([
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        "bP . .",
        ". . .",
        "wP . .",
    ])
    assert is_legal_pawn_move(board, "wP", 7, 0, 5, 0) is False


def test_pawn_cannot_capture_with_double_step():
    # Enemy piece diagonally 2 rows away — not a valid pawn move.
    board = make_board([
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". bR .",
        ". . .",
        "wP . .",
    ])
    # two-square diagonal is not a pawn move at all
    assert is_legal_pawn_move(board, "wP", 7, 0, 5, 1) is False
