import pytest
from game.rules.rule_engine import RuleEngine, MoveValidation


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_board(rows):
    """Build a board from a list of space-separated strings."""
    return [row.split() for row in rows]


@pytest.fixture
def engine():
    return RuleEngine()


# ---------------------------------------------------------------------------
# A. Legal move — result.is_valid is True, result.reason == "ok"
# ---------------------------------------------------------------------------

def test_legal_rook_move(engine):
    board = make_board(["wR . . . ."])
    result = engine.validate_move(board, 0, 0, 0, 4)
    assert result.is_valid is True
    assert result.reason == "ok"


def test_legal_knight_move(engine):
    board = make_board([
        "wN . .",
        ". . .",
        ". . .",
    ])
    result = engine.validate_move(board, 0, 0, 2, 1)
    assert result.is_valid is True
    assert result.reason == "ok"


def test_legal_king_move(engine):
    board = make_board([
        ". . .",
        ". wK .",
        ". . .",
    ])
    result = engine.validate_move(board, 1, 1, 0, 0)
    assert result.is_valid is True
    assert result.reason == "ok"


def test_legal_capture_returns_ok(engine):
    board = make_board(["wR . . bR"])
    result = engine.validate_move(board, 0, 0, 0, 3)
    assert result.is_valid is True
    assert result.reason == "ok"


# ---------------------------------------------------------------------------
# B. Source outside board — reason == "outside_board"
# ---------------------------------------------------------------------------

def test_source_row_negative(engine):
    board = make_board(["wR . ."])
    result = engine.validate_move(board, -1, 0, 0, 0)
    assert result.is_valid is False
    assert result.reason == "outside_board"


def test_source_row_too_large(engine):
    board = make_board(["wR . ."])
    result = engine.validate_move(board, 5, 0, 0, 0)
    assert result.is_valid is False
    assert result.reason == "outside_board"


def test_source_col_too_large(engine):
    board = make_board(["wR . ."])
    result = engine.validate_move(board, 0, 10, 0, 0)
    assert result.is_valid is False
    assert result.reason == "outside_board"


# ---------------------------------------------------------------------------
# C. Destination outside board — reason == "outside_board"
# ---------------------------------------------------------------------------

def test_destination_row_negative(engine):
    board = make_board(["wR . ."])
    result = engine.validate_move(board, 0, 0, -1, 0)
    assert result.is_valid is False
    assert result.reason == "outside_board"


def test_destination_col_too_large(engine):
    board = make_board(["wR . ."])
    result = engine.validate_move(board, 0, 0, 0, 10)
    assert result.is_valid is False
    assert result.reason == "outside_board"


# ---------------------------------------------------------------------------
# D. Empty source — reason == "empty_source"
# ---------------------------------------------------------------------------

def test_empty_source_cell(engine):
    board = make_board([". . ."])
    result = engine.validate_move(board, 0, 0, 0, 2)
    assert result.is_valid is False
    assert result.reason == "empty_source"


def test_empty_source_with_pieces_elsewhere(engine):
    board = make_board(["wR . ."])
    result = engine.validate_move(board, 0, 1, 0, 2)
    assert result.is_valid is False
    assert result.reason == "empty_source"


# ---------------------------------------------------------------------------
# E. Friendly destination — reason == "friendly_destination"
# ---------------------------------------------------------------------------

def test_friendly_destination_same_color(engine):
    board = make_board(["wR wB ."])
    result = engine.validate_move(board, 0, 0, 0, 1)
    assert result.is_valid is False
    assert result.reason == "friendly_destination"


def test_friendly_destination_knight(engine):
    board = make_board([
        ". wP .",
        ". . .",
        "wN . .",
    ])
    result = engine.validate_move(board, 2, 0, 0, 1)
    assert result.is_valid is False
    assert result.reason == "friendly_destination"


# ---------------------------------------------------------------------------
# F. Illegal non-pawn movement shape — reason == "illegal_piece_move"
# ---------------------------------------------------------------------------

def test_rook_diagonal_is_illegal(engine):
    board = make_board([
        "wR . .",
        ". . .",
        ". . .",
    ])
    result = engine.validate_move(board, 0, 0, 2, 2)
    assert result.is_valid is False
    assert result.reason == "illegal_piece_move"


def test_bishop_horizontal_is_illegal(engine):
    board = make_board(["wB . . ."])
    result = engine.validate_move(board, 0, 0, 0, 3)
    assert result.is_valid is False
    assert result.reason == "illegal_piece_move"


def test_knight_straight_is_illegal(engine):
    board = make_board([
        "wN . .",
        ". . .",
        ". . .",
    ])
    result = engine.validate_move(board, 0, 0, 2, 0)
    assert result.is_valid is False
    assert result.reason == "illegal_piece_move"


# ---------------------------------------------------------------------------
# G. Blocked sliding-piece path — reason == "illegal_piece_move"
# ---------------------------------------------------------------------------

def test_rook_blocked_by_piece_in_path(engine):
    board = make_board(["wR bP . ."])
    result = engine.validate_move(board, 0, 0, 0, 3)
    assert result.is_valid is False
    assert result.reason == "illegal_piece_move"


def test_bishop_blocked_by_piece_in_path(engine):
    board = make_board([
        "wB . . .",
        ". bP . .",
        ". . . .",
        ". . . .",
    ])
    result = engine.validate_move(board, 0, 0, 3, 3)
    assert result.is_valid is False
    assert result.reason == "illegal_piece_move"


def test_queen_blocked_by_piece_in_path(engine):
    board = make_board([
        "wQ . . .",
        ". . . .",
        ". . wP .",
        ". . . .",
    ])
    # queen tries diagonal from (0,0) to (3,3), blocked by wP at (2,2)
    # but wP is friendly → friendly_destination would trigger first?
    # Actually the source piece is at (0,0)=wQ, target (3,3)=".".
    # Path check: (1,1)=".". (2,2)="wP" ≠ "." → blocked.
    result = engine.validate_move(board, 0, 0, 3, 3)
    assert result.is_valid is False
    assert result.reason == "illegal_piece_move"


# ---------------------------------------------------------------------------
# H. Illegal pawn move — reason == "illegal_piece_move"
# ---------------------------------------------------------------------------

def test_pawn_sideways_is_illegal(engine):
    board = make_board([
        ". . .",
        "wP . .",
        ". . .",
        ". . .",
    ])
    result = engine.validate_move(board, 1, 0, 1, 1)
    assert result.is_valid is False
    assert result.reason == "illegal_piece_move"


def test_pawn_backward_is_illegal(engine):
    board = make_board([
        ". . .",
        "wP . .",
        ". . .",
        ". . .",
    ])
    # White pawn cannot move downward (row 1 → row 2)
    result = engine.validate_move(board, 1, 0, 2, 0)
    assert result.is_valid is False
    assert result.reason == "illegal_piece_move"


def test_pawn_forward_blocked_by_piece(engine):
    board = make_board([
        "bR . .",
        "wP . .",
        ". . .",
        ". . .",
    ])
    # Forward into occupied square
    result = engine.validate_move(board, 1, 0, 0, 0)
    assert result.is_valid is False
    assert result.reason == "illegal_piece_move"


def test_pawn_diagonal_without_enemy_is_illegal(engine):
    board = make_board([
        ". . .",
        "wP . .",
        ". . .",
        ". . .",
    ])
    result = engine.validate_move(board, 1, 0, 0, 1)
    assert result.is_valid is False
    assert result.reason == "illegal_piece_move"


# ---------------------------------------------------------------------------
# I. Legal pawn move — result.is_valid is True, reason == "ok"
# ---------------------------------------------------------------------------

def test_pawn_forward_one_square(engine):
    board = make_board([
        ". . .",
        "wP . .",
        ". . .",
        ". . .",
    ])
    result = engine.validate_move(board, 1, 0, 0, 0)
    # wait — (0,0) is ".", so forward into empty is legal
    # re-check: board[0][0] = "." so this should be ok
    # BUT test H above uses the same board with bR at (0,0).
    # Here (0,0) is "." → legal forward move.
    assert result.is_valid is True
    assert result.reason == "ok"


def test_pawn_diagonal_capture(engine):
    board = make_board([
        ". bR .",
        "wP . .",
        ". . .",
        ". . .",
    ])
    result = engine.validate_move(board, 1, 0, 0, 1)
    assert result.is_valid is True
    assert result.reason == "ok"


def test_black_pawn_forward_one_square(engine):
    board = make_board([
        ". . .",
        ". . .",
        "bP . .",
        ". . .",
    ])
    result = engine.validate_move(board, 2, 0, 3, 0)
    assert result.is_valid is True
    assert result.reason == "ok"


def test_pawn_double_step_from_starting_row(engine):
    # 8-row board. White starting row = 7.
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
    result = engine.validate_move(board, 7, 0, 5, 0)
    assert result.is_valid is True
    assert result.reason == "ok"


# ---------------------------------------------------------------------------
# MoveValidation dataclass
# ---------------------------------------------------------------------------

def test_move_validation_is_immutable():
    mv = MoveValidation(is_valid=True, reason="ok")
    with pytest.raises(Exception):
        mv.is_valid = False


def test_move_validation_equality():
    a = MoveValidation(is_valid=True, reason="ok")
    b = MoveValidation(is_valid=True, reason="ok")
    assert a == b


# ===========================================================================
# validate_jump
# ===========================================================================

from game.rules.rule_engine import JumpValidation


def test_jump_outside_board_invalid(engine):
    board = make_board(["wR . ."])
    result = engine.validate_jump(board, 5, 0, is_piece_moving=False, is_airborne=False)
    assert result.is_valid is False
    assert result.reason == "outside_board"


def test_jump_negative_row_invalid(engine):
    board = make_board(["wR . ."])
    result = engine.validate_jump(board, -1, 0, is_piece_moving=False, is_airborne=False)
    assert result.is_valid is False
    assert result.reason == "outside_board"


def test_jump_empty_source_invalid(engine):
    board = make_board(["wR . ."])
    result = engine.validate_jump(board, 0, 1, is_piece_moving=False, is_airborne=False)
    assert result.is_valid is False
    assert result.reason == "empty_source"


def test_jump_piece_moving_invalid(engine):
    board = make_board(["wR . ."])
    result = engine.validate_jump(board, 0, 0, is_piece_moving=True, is_airborne=False)
    assert result.is_valid is False
    assert result.reason == "piece_moving"


def test_jump_already_airborne_invalid(engine):
    board = make_board(["wR . ."])
    result = engine.validate_jump(board, 0, 0, is_piece_moving=False, is_airborne=True)
    assert result.is_valid is False
    assert result.reason == "already_airborne"


def test_jump_valid(engine):
    board = make_board(["wR . ."])
    result = engine.validate_jump(board, 0, 0, is_piece_moving=False, is_airborne=False)
    assert result.is_valid is True
    assert result.reason == "ok"


def test_jump_validation_is_jump_validation_instance(engine):
    board = make_board(["wR . ."])
    result = engine.validate_jump(board, 0, 0, is_piece_moving=False, is_airborne=False)
    assert isinstance(result, JumpValidation)
