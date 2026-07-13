import pytest
from game.engine.game_engine import GameEngine, MoveResult
from game.realtime.motion import PendingMove


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_board(rows):
    """Build a board from a list of space-separated strings."""
    return [row.split() for row in rows]


# ---------------------------------------------------------------------------
# A. Legal move — is_accepted True, reason "ok", one PendingMove created
# ---------------------------------------------------------------------------

def test_legal_move_is_accepted():
    board = make_board(["wR . . . ."])
    engine = GameEngine(board)
    result = engine.request_move(0, 0, 0, 4)
    assert result.is_accepted is True
    assert result.reason == "ok"


def test_legal_move_creates_one_pending_move():
    board = make_board(["wR . . . ."])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 4)
    assert len(engine.pending_moves) == 1
    move = engine.pending_moves[0]
    assert move.piece == "wR"
    assert move.from_row == 0
    assert move.from_col == 0
    assert move.to_row == 0
    assert move.to_col == 4


def test_legal_move_result_is_move_result_instance():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    result = engine.request_move(0, 0, 0, 2)
    assert isinstance(result, MoveResult)


# ---------------------------------------------------------------------------
# B. Game already over — is_accepted False, reason "game_over"
# ---------------------------------------------------------------------------

def test_game_over_rejects_move():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    engine.game_over = True
    result = engine.request_move(0, 0, 0, 2)
    assert result.is_accepted is False
    assert result.reason == "game_over"


def test_game_over_does_not_create_pending_move():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    engine.game_over = True
    engine.request_move(0, 0, 0, 2)
    assert len(engine.pending_moves) == 0


# ---------------------------------------------------------------------------
# C. Destination already claimed — is_accepted False, reason "destination_claimed"
# ---------------------------------------------------------------------------

def test_destination_claimed_rejects_move():
    board = make_board([
        "wR . . . .",
        "wR . . . .",
    ])
    engine = GameEngine(board)
    # First move claims (0, 4)
    engine.request_move(0, 0, 0, 4)
    # Second move tries the same destination
    result = engine.request_move(1, 0, 0, 4)
    assert result.is_accepted is False
    assert result.reason == "destination_claimed"


def test_destination_claimed_does_not_add_pending_move():
    board = make_board([
        "wR . . . .",
        "wR . . . .",
    ])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 4)
    engine.request_move(1, 0, 0, 4)
    assert len(engine.pending_moves) == 1  # only the first


# ---------------------------------------------------------------------------
# D. RuleEngine rejects with "outside_board"
# ---------------------------------------------------------------------------

def test_outside_board_source_rejected():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    result = engine.request_move(-1, 0, 0, 0)
    assert result.is_accepted is False
    assert result.reason == "outside_board"


def test_outside_board_destination_rejected():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    result = engine.request_move(0, 0, 0, 10)
    assert result.is_accepted is False
    assert result.reason == "outside_board"


# ---------------------------------------------------------------------------
# E. RuleEngine rejects with "empty_source"
# ---------------------------------------------------------------------------

def test_empty_source_rejected():
    board = make_board([". . ."])
    engine = GameEngine(board)
    result = engine.request_move(0, 0, 0, 2)
    assert result.is_accepted is False
    assert result.reason == "empty_source"


# ---------------------------------------------------------------------------
# F. RuleEngine rejects with "friendly_destination"
# ---------------------------------------------------------------------------

def test_friendly_destination_rejected():
    board = make_board(["wR wB ."])
    engine = GameEngine(board)
    result = engine.request_move(0, 0, 0, 1)
    assert result.is_accepted is False
    assert result.reason == "friendly_destination"


# ---------------------------------------------------------------------------
# G. RuleEngine rejects with "illegal_piece_move"
# ---------------------------------------------------------------------------

def test_illegal_piece_move_rook_diagonal():
    board = make_board([
        "wR . .",
        ". . .",
        ". . .",
    ])
    engine = GameEngine(board)
    result = engine.request_move(0, 0, 2, 2)
    assert result.is_accepted is False
    assert result.reason == "illegal_piece_move"


def test_illegal_piece_move_blocked_path():
    board = make_board(["wR bP . ."])
    engine = GameEngine(board)
    result = engine.request_move(0, 0, 0, 3)
    assert result.is_accepted is False
    assert result.reason == "illegal_piece_move"


def test_illegal_piece_move_pawn_sideways():
    board = make_board([
        ". . .",
        "wP . .",
        ". . .",
        ". . .",
    ])
    engine = GameEngine(board)
    result = engine.request_move(1, 0, 1, 1)
    assert result.is_accepted is False
    assert result.reason == "illegal_piece_move"


# ---------------------------------------------------------------------------
# MoveResult dataclass
# ---------------------------------------------------------------------------

def test_move_result_is_immutable():
    mr = MoveResult(is_accepted=True, reason="ok")
    with pytest.raises(Exception):
        mr.is_accepted = False


def test_move_result_equality():
    a = MoveResult(is_accepted=True, reason="ok")
    b = MoveResult(is_accepted=True, reason="ok")
    assert a == b


# ===========================================================================
# Jump validation through GameEngine
# ===========================================================================

def test_game_over_rejects_jump_before_validation():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    engine.game_over = True
    result = engine.request_jump(0, 0)
    assert result is False
    assert len(engine.active_jumps) == 0


def test_invalid_jump_does_not_create_active_jump():
    board = make_board([". . ."])  # empty — no piece to jump
    engine = GameEngine(board)
    result = engine.request_jump(0, 0)
    assert result is False
    assert len(engine.active_jumps) == 0


def test_valid_jump_creates_exactly_one_active_jump():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    result = engine.request_jump(0, 0)
    assert result is True
    assert len(engine.active_jumps) == 1
    jump = engine.active_jumps[0]
    assert jump.piece == "wR"
    assert jump.row == 0
    assert jump.col == 0


def test_controller_jump_still_returns_bool():
    from game.controller.controller import Controller
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    ctrl = Controller(engine)
    result = ctrl.jump(50, 50)
    assert result is True
    assert isinstance(result, bool)


def test_controller_jump_returns_false_on_empty():
    from game.controller.controller import Controller
    board = make_board([". . ."])
    engine = GameEngine(board)
    ctrl = Controller(engine)
    result = ctrl.jump(50, 50)
    assert result is False
    assert isinstance(result, bool)
