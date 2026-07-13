"""
Tests for the cooldown / resting mechanic.

A piece that arrives at its destination enters a cooldown period
during which it cannot be selected, moved, or jumped.
"""
import pytest
from game.engine.game_engine import GameEngine, MoveResult
from game.controller.controller import Controller
from game.io.command_runner import process_commands
from game.model.constants import MOVE_DURATION_MS, COOLDOWN_DURATION_MS
from game.realtime.real_time_arbiter import RealTimeArbiter
from game.realtime.motion import PendingMove


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_board(rows):
    return [row.split() for row in rows]


# ===========================================================================
# RealTimeArbiter — cooldown management
# ===========================================================================

def test_start_cooldown_adds_cooldown_with_correct_available_at():
    arbiter = RealTimeArbiter()
    arbiter.clock = 2000
    arbiter.start_cooldown("wR", 0, 2)
    assert len(arbiter.active_cooldowns) == 1
    cd = arbiter.active_cooldowns[0]
    assert cd.row == 0
    assert cd.col == 2
    assert cd.available_at == 3000  # 2000 + COOLDOWN_DURATION_MS


def test_piece_is_resting_before_available_at():
    arbiter = RealTimeArbiter()
    arbiter.clock = 2000
    arbiter.start_cooldown("wR", 0, 2)
    arbiter.clock = 2999
    assert arbiter.is_piece_resting_at(0, 2) is True


def test_piece_is_available_at_exact_available_at():
    arbiter = RealTimeArbiter()
    arbiter.clock = 2000
    arbiter.start_cooldown("wR", 0, 2)
    arbiter.clock = 3000
    assert arbiter.is_piece_resting_at(0, 2) is False


def test_expire_cooldowns_removes_expired():
    arbiter = RealTimeArbiter()
    arbiter.clock = 0
    arbiter.start_cooldown("wR", 0, 0)
    arbiter.clock = COOLDOWN_DURATION_MS
    arbiter.expire_cooldowns()
    assert len(arbiter.active_cooldowns) == 0


def test_multiple_cooldowns_coexist():
    arbiter = RealTimeArbiter()
    arbiter.clock = 0
    arbiter.start_cooldown("wR", 0, 0)
    arbiter.clock = 500
    arbiter.start_cooldown("wB", 1, 1)
    # At clock=500: both resting
    assert arbiter.is_piece_resting_at(0, 0) is True
    assert arbiter.is_piece_resting_at(1, 1) is True


def test_expiring_one_cooldown_does_not_affect_another():
    arbiter = RealTimeArbiter()
    arbiter.clock = 0
    arbiter.start_cooldown("wR", 0, 0)  # available_at=1000
    arbiter.clock = 500
    arbiter.start_cooldown("wB", 1, 1)  # available_at=1500
    arbiter.clock = 1000
    arbiter.expire_cooldowns()
    assert arbiter.is_piece_resting_at(0, 0) is False
    assert arbiter.is_piece_resting_at(1, 1) is True


# ===========================================================================
# MovementResolver — cooldown triggered on successful arrival
# ===========================================================================

def test_successful_arrival_creates_cooldown():
    arbiter = RealTimeArbiter()
    board = make_board(["wR . ."])
    arbiter.start_motion("wR", 0, 0, 0, 1)
    arbiter.advance_time(board, MOVE_DURATION_MS)
    # After arrival, piece should be resting at destination
    assert arbiter.is_piece_resting_at(0, 1) is True


def test_move_still_in_flight_does_not_create_cooldown():
    arbiter = RealTimeArbiter()
    board = make_board(["wR . ."])
    arbiter.start_motion("wR", 0, 0, 0, 1)
    arbiter.advance_time(board, MOVE_DURATION_MS - 1)
    assert arbiter.is_piece_resting_at(0, 1) is False


def test_cancelled_move_does_not_create_cooldown():
    arbiter = RealTimeArbiter()
    board = make_board([". . ."])  # piece already gone from source
    arbiter.pending_moves = [PendingMove("wR", 0, 0, 0, 2, arrive_at=1000)]
    arbiter.advance_time(board, 1000)
    assert arbiter.is_piece_resting_at(0, 2) is False


def test_capture_creates_cooldown():
    arbiter = RealTimeArbiter()
    board = make_board(["wR bP ."])
    arbiter.start_motion("wR", 0, 0, 0, 1)
    arbiter.advance_time(board, MOVE_DURATION_MS)
    assert arbiter.is_piece_resting_at(0, 1) is True


def test_promotion_creates_cooldown():
    arbiter = RealTimeArbiter()
    # 3-row board: white promotion row = 0
    board = make_board([".", "wP", "."])
    arbiter.start_motion("wP", 1, 0, 0, 0)
    arbiter.advance_time(board, MOVE_DURATION_MS)
    # Pawn promoted to queen, cooldown still at destination
    assert arbiter.is_piece_resting_at(0, 0) is True


def test_airborne_capture_does_not_create_cooldown_for_destroyed_piece():
    """If a moving piece is destroyed by an airborne enemy, no cooldown."""
    from game.realtime.motion import ActiveJump
    arbiter = RealTimeArbiter()
    board = make_board(["wR . bR"])
    # bR is airborne at (0,2)
    arbiter.active_jumps = [ActiveJump(piece="bR", row=0, col=2, expires_at=5000)]
    arbiter.start_motion("wR", 0, 0, 0, 2)
    arbiter.advance_time(board, 2 * MOVE_DURATION_MS)
    # wR was destroyed, no cooldown at (0,2) for wR
    assert arbiter.is_piece_resting_at(0, 2) is False


# ===========================================================================
# GameEngine — rejection when piece is resting
# ===========================================================================

def test_request_move_from_resting_piece_rejected():
    board = make_board(["wR . . ."])
    engine = GameEngine(board)
    # Move wR to col 1, let it arrive
    engine.request_move(0, 0, 0, 1)
    engine.handle_wait(MOVE_DURATION_MS)
    # Now try to move it again — should be rejected
    result = engine.request_move(0, 1, 0, 3)
    assert result.is_accepted is False
    assert result.reason == "piece_resting"


def test_request_jump_from_resting_piece_rejected():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 1)
    engine.handle_wait(MOVE_DURATION_MS)
    result = engine.request_jump(0, 1)
    assert result is False


def test_piece_movable_after_cooldown_expires():
    board = make_board(["wR . . ."])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 1)
    engine.handle_wait(MOVE_DURATION_MS)
    # Wait for cooldown to expire
    engine.handle_wait(COOLDOWN_DURATION_MS)
    result = engine.request_move(0, 1, 0, 3)
    assert result.is_accepted is True


def test_other_piece_can_move_while_one_is_resting():
    board = make_board(["wR . . wR . ."])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 1)
    engine.handle_wait(MOVE_DURATION_MS)
    # First wR is resting at (0,1), second wR at (0,3) should be free
    result = engine.request_move(0, 3, 0, 5)
    assert result.is_accepted is True


def test_direct_request_move_without_controller_rejects_resting():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 1)
    engine.handle_wait(MOVE_DURATION_MS)
    result = engine.request_move(0, 1, 0, 2)
    assert result.is_accepted is False
    assert result.reason == "piece_resting"


# ===========================================================================
# Controller — cannot select resting piece
# ===========================================================================

def test_click_on_resting_piece_does_not_select():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    ctrl = Controller(engine)
    # Move and arrive
    ctrl.click(0, 0)   # select
    ctrl.click(100, 0) # move to col 1
    engine.handle_wait(MOVE_DURATION_MS)
    # Try to select resting piece
    ctrl.click(100, 0)
    assert ctrl.selected is None


def test_click_on_non_resting_piece_still_selects():
    board = make_board(["wR . wB ."])
    engine = GameEngine(board)
    ctrl = Controller(engine)
    # Move wR and arrive
    ctrl.click(0, 0)
    ctrl.click(100, 0)
    engine.handle_wait(MOVE_DURATION_MS)
    # Select wB — should work
    ctrl.click(200, 0)
    assert ctrl.selected == (0, 2)


def test_switch_selection_to_resting_friendly_piece_blocked():
    board = make_board(["wR . wB ."])
    engine = GameEngine(board)
    ctrl = Controller(engine)
    # Move wR to col 1 and arrive
    ctrl.click(0, 0)
    ctrl.click(100, 0)
    engine.handle_wait(MOVE_DURATION_MS)
    # Select wB (non-resting)
    ctrl.click(200, 0)
    assert ctrl.selected == (0, 2)
    # Try to switch to resting wR at col 1
    ctrl.click(100, 0)
    # Should keep wB selected
    assert ctrl.selected == (0, 2)


# ===========================================================================
# Integration — full flow
# ===========================================================================

def test_full_cooldown_flow(capsys):
    board = make_board(["wR . . ."])
    commands = [
        "click 50 50",              # select wR
        "click 150 50",             # move to col 1
        f"wait {MOVE_DURATION_MS}", # wR arrives, enters cooldown
        "click 150 50",             # try to select resting wR — fails
        "click 250 50",             # nothing selected, ignored
        f"wait {COOLDOWN_DURATION_MS}",  # cooldown expires
        "click 150 50",             # select wR again
        "click 250 50",             # move to col 2
        f"wait {MOVE_DURATION_MS}", # arrives
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == ". . wR ."


# ===========================================================================
# Edge cases
# ===========================================================================

def test_wait_zero_does_not_expire_cooldown():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 1)
    engine.handle_wait(MOVE_DURATION_MS)
    engine.handle_wait(0)
    # Still resting
    result = engine.request_move(0, 1, 0, 2)
    assert result.is_accepted is False
    assert result.reason == "piece_resting"


def test_cooldown_starts_at_arrival_clock_not_move_creation():
    board = make_board(["wR . . ."])
    engine = GameEngine(board)
    # Wait 500ms, then start move
    engine.handle_wait(500)
    engine.request_move(0, 0, 0, 1)
    # Move arrives at 500 + 1000 = 1500
    engine.handle_wait(MOVE_DURATION_MS)
    # Cooldown available_at = 1500 + 1000 = 2500
    # At clock=1500: resting
    assert engine.arbiter.is_piece_resting_at(0, 1) is True
    # Advance to 2500: available
    engine.handle_wait(COOLDOWN_DURATION_MS)
    assert engine.arbiter.is_piece_resting_at(0, 1) is False


def test_captured_resting_piece_cooldown_does_not_block_new_piece():
    """If a resting piece is captured, its cooldown should not block
    a different piece that later moves into the same cell."""
    board = make_board(["wR . . bR"])
    engine = GameEngine(board)
    # wR moves to col 1
    engine.request_move(0, 0, 0, 1)
    engine.handle_wait(MOVE_DURATION_MS)
    # wR is now resting at (0,1)
    # bR captures wR at (0,1) — moves from col 3 to col 1
    engine.request_move(0, 3, 0, 1)
    engine.handle_wait(3 * MOVE_DURATION_MS)  # distance 2, but wait enough
    # After bR arrives and captures, the old wR cooldown should not block bR
    # bR now has its OWN cooldown at (0,1), not wR's
    assert board[0][1] == "bR"
