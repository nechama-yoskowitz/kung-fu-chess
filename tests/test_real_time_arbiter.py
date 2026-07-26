import pytest
from game.realtime.real_time_arbiter import RealTimeArbiter
from game.model.constants import MOVE_DURATION_MS, JUMP_DURATION_MS
from game.model.piece import WHITE_ROOK, WHITE_BISHOP, BLACK_ROOK, BLACK_PAWN
from game.io.piece_token_codec import parse_board


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_board(rows):
    """Build a board from a list of space-separated strings."""
    return parse_board([row.split() for row in rows])


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

def test_starts_with_clock_zero():
    arbiter = RealTimeArbiter()
    assert arbiter.clock == 0


def test_starts_with_no_pending_moves():
    arbiter = RealTimeArbiter()
    assert arbiter.pending_moves == []


def test_starts_with_no_active_jumps():
    arbiter = RealTimeArbiter()
    assert arbiter.active_jumps == []


# ---------------------------------------------------------------------------
# start_motion
# ---------------------------------------------------------------------------

def test_start_motion_creates_one_pending_move():
    arbiter = RealTimeArbiter()
    result = arbiter.start_motion(WHITE_ROOK, 0, 0, 0, 4)
    assert result is True
    assert len(arbiter.pending_moves) == 1
    move = arbiter.pending_moves[0]
    assert move.piece == WHITE_ROOK
    assert move.from_row == 0
    assert move.from_col == 0
    assert move.to_row == 0
    assert move.to_col == 4
    assert move.arrive_at == 4 * MOVE_DURATION_MS


def test_start_motion_uses_current_clock():
    arbiter = RealTimeArbiter()
    arbiter.clock = 500
    arbiter.start_motion(WHITE_ROOK, 0, 0, 0, 2)
    assert arbiter.pending_moves[0].arrive_at == 500 + 2 * MOVE_DURATION_MS


# ---------------------------------------------------------------------------
# start_jump
# ---------------------------------------------------------------------------

def test_start_jump_creates_one_active_jump():
    arbiter = RealTimeArbiter()
    result = arbiter.start_jump(WHITE_ROOK, 0, 0)
    assert result is True
    assert len(arbiter.active_jumps) == 1
    jump = arbiter.active_jumps[0]
    assert jump.piece == WHITE_ROOK
    assert jump.row == 0
    assert jump.col == 0
    assert jump.expires_at == JUMP_DURATION_MS


def test_start_jump_uses_current_clock():
    arbiter = RealTimeArbiter()
    arbiter.clock = 300
    arbiter.start_jump(BLACK_ROOK, 1, 2)
    assert arbiter.active_jumps[0].expires_at == 300 + JUMP_DURATION_MS


# ---------------------------------------------------------------------------
# is_piece_moving_at
# ---------------------------------------------------------------------------

def test_is_piece_moving_at_returns_true_when_pending():
    arbiter = RealTimeArbiter()
    arbiter.start_motion(WHITE_ROOK, 0, 0, 0, 4)
    assert arbiter.is_piece_moving_at(0, 0) is True


def test_is_piece_moving_at_returns_false_when_no_pending():
    arbiter = RealTimeArbiter()
    assert arbiter.is_piece_moving_at(0, 0) is False


def test_is_piece_moving_at_returns_false_for_other_cell():
    arbiter = RealTimeArbiter()
    arbiter.start_motion(WHITE_ROOK, 0, 0, 0, 4)
    assert arbiter.is_piece_moving_at(1, 1) is False


# ---------------------------------------------------------------------------
# is_airborne_at
# ---------------------------------------------------------------------------

def test_is_airborne_at_returns_true_when_jumping():
    arbiter = RealTimeArbiter()
    arbiter.start_jump(WHITE_ROOK, 2, 3)
    assert arbiter.is_airborne_at(2, 3) is True


def test_is_airborne_at_returns_false_when_not_jumping():
    arbiter = RealTimeArbiter()
    assert arbiter.is_airborne_at(0, 0) is False


# ---------------------------------------------------------------------------
# has_active_motion
# ---------------------------------------------------------------------------

def test_has_active_motion_true_when_moves_pending():
    arbiter = RealTimeArbiter()
    arbiter.start_motion(WHITE_ROOK, 0, 0, 0, 2)
    assert arbiter.has_active_motion() is True


def test_has_active_motion_false_when_empty():
    arbiter = RealTimeArbiter()
    assert arbiter.has_active_motion() is False


# ---------------------------------------------------------------------------
# advance_time
# ---------------------------------------------------------------------------

def test_advance_time_accumulates_clock():
    arbiter = RealTimeArbiter()
    board = make_board(["wR . ."])
    arbiter.advance_time(board, 200)
    assert arbiter.clock == 200
    arbiter.advance_time(board, 300)
    assert arbiter.clock == 500


def test_advance_time_returns_false_when_no_game_over():
    arbiter = RealTimeArbiter()
    board = make_board(["wR . ."])
    arbiter.start_motion(WHITE_ROOK, 0, 0, 0, 2)
    result = arbiter.advance_time(board, 2 * MOVE_DURATION_MS)
    assert result is False


# ---------------------------------------------------------------------------
# Move does not arrive before its time
# ---------------------------------------------------------------------------

def test_move_does_not_arrive_before_time():
    arbiter = RealTimeArbiter()
    board = make_board(["wR . ."])
    arbiter.start_motion(WHITE_ROOK, 0, 0, 0, 2)
    arbiter.advance_time(board, 2 * MOVE_DURATION_MS - 1)
    # Piece still at source
    assert board[0][0] == WHITE_ROOK
    assert board[0][2] is None
    assert len(arbiter.pending_moves) == 1


# ---------------------------------------------------------------------------
# Move arrives exactly at its time
# ---------------------------------------------------------------------------

def test_move_arrives_exactly_at_time():
    arbiter = RealTimeArbiter()
    board = make_board(["wR . ."])
    arbiter.start_motion(WHITE_ROOK, 0, 0, 0, 2)
    arbiter.advance_time(board, 2 * MOVE_DURATION_MS)
    # Piece has arrived
    assert board[0][0] is None
    assert board[0][2] == WHITE_ROOK
    assert len(arbiter.pending_moves) == 0


# ---------------------------------------------------------------------------
# Expired jumps are removed
# ---------------------------------------------------------------------------

def test_expired_jumps_removed():
    arbiter = RealTimeArbiter()
    board = make_board(["wR . ."])
    arbiter.start_jump(WHITE_ROOK, 0, 0)
    # Jump expires at JUMP_DURATION_MS. Advance past it.
    arbiter.advance_time(board, JUMP_DURATION_MS + 1)
    assert len(arbiter.active_jumps) == 0


def test_jump_not_expired_at_exact_time():
    arbiter = RealTimeArbiter()
    board = make_board(["wR . ."])
    arbiter.start_jump(WHITE_ROOK, 0, 0)
    arbiter.advance_time(board, JUMP_DURATION_MS)
    # At exact expiry time the jump is still active
    assert len(arbiter.active_jumps) == 1


# ---------------------------------------------------------------------------
# Capture resolved on arrival
# ---------------------------------------------------------------------------

def test_capture_resolved_on_arrival():
    arbiter = RealTimeArbiter()
    board = make_board(["wR . bP"])
    arbiter.start_motion(WHITE_ROOK, 0, 0, 0, 2)
    arbiter.advance_time(board, 2 * MOVE_DURATION_MS)
    assert board[0][2] == WHITE_ROOK
    assert board[0][0] is None


# ---------------------------------------------------------------------------
# King capture reports game over
# ---------------------------------------------------------------------------

def test_king_capture_reports_game_over():
    arbiter = RealTimeArbiter()
    board = make_board(["wR . bK"])
    arbiter.start_motion(WHITE_ROOK, 0, 0, 0, 2)
    game_over = arbiter.advance_time(board, 2 * MOVE_DURATION_MS)
    assert game_over is True
    assert board[0][2] == WHITE_ROOK


def test_king_capture_clears_pending_moves():
    arbiter = RealTimeArbiter()
    board = make_board(["wR . bK", "wB . . "])
    arbiter.start_motion(WHITE_ROOK, 0, 0, 0, 2)
    arbiter.start_motion(WHITE_BISHOP, 1, 0, 1, 2)
    arbiter.advance_time(board, 2 * MOVE_DURATION_MS)
    # wR captures king → game over → wB cancelled
    assert len(arbiter.pending_moves) == 0
    assert board[1][0] == WHITE_BISHOP  # wB never moved


# ---------------------------------------------------------------------------
# is_destination_claimed
# ---------------------------------------------------------------------------

def test_is_destination_claimed_true():
    arbiter = RealTimeArbiter()
    arbiter.start_motion(WHITE_ROOK, 0, 0, 0, 2)
    assert arbiter.is_destination_claimed(0, 2) is True


def test_is_destination_claimed_false():
    arbiter = RealTimeArbiter()
    assert arbiter.is_destination_claimed(0, 2) is False
