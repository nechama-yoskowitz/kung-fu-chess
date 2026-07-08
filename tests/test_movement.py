import pytest
from game.movement import PendingMove, apply_arrived_moves, is_piece_moving
from game.commands import handle_click, process_commands
from game.constants import MOVE_DURATION_MS


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_board(rows):
    """Build a board from a list of space-separated strings."""
    return [row.split() for row in rows]


def make_move(piece, from_row, from_col, to_row, to_col, arrive_at):
    return PendingMove(piece, from_row, from_col, to_row, to_col, arrive_at)


# ---------------------------------------------------------------------------
# apply_arrived_moves
# ---------------------------------------------------------------------------

def test_move_does_not_arrive_before_time():
    board = make_board(["wR . ."])
    pending = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    remaining = apply_arrived_moves(board, pending, clock=999)
    assert board[0][0] == "wR"
    assert board[0][2] == "."
    assert len(remaining) == 1


def test_move_does_not_arrive_exactly_at_time():
    # arrive_at is exclusive: the piece is still in transit at t == arrive_at
    board = make_board(["wR . ."])
    pending = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    remaining = apply_arrived_moves(board, pending, clock=1000)
    assert board[0][0] == "wR"
    assert board[0][2] == "."
    assert len(remaining) == 1


def test_move_arrives_after_time():
    board = make_board(["wR . ."])
    pending = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    remaining = apply_arrived_moves(board, pending, clock=1001)
    assert board[0][2] == "wR"
    assert board[0][0] == "."
    assert len(remaining) == 0


def test_only_arrived_moves_are_applied():
    board = make_board(["wR . . . wB"])
    pending = [
        make_move("wR", 0, 0, 0, 1, arrive_at=500),
        make_move("wB", 0, 4, 0, 3, arrive_at=2000),
    ]
    remaining = apply_arrived_moves(board, pending, clock=1000)
    # wR has arrived (arrive_at=500 < clock=1000)
    assert board[0][1] == "wR"
    assert board[0][0] == "."
    # wB has not arrived yet (arrive_at=2000 > clock=1000)
    assert board[0][4] == "wB"
    assert board[0][3] == "."
    assert len(remaining) == 1


def test_multiple_moves_arrive_at_same_time():
    board = make_board([
        "wR . .",
        "wB . .",
    ])
    pending = [
        make_move("wR", 0, 0, 0, 2, arrive_at=1000),
        make_move("wB", 1, 0, 1, 2, arrive_at=1000),
    ]
    # clock must be strictly greater than arrive_at
    remaining = apply_arrived_moves(board, pending, clock=1001)
    assert board[0][2] == "wR"
    assert board[1][2] == "wB"
    assert len(remaining) == 0


def test_arrived_move_captures_enemy():
    board = make_board(["wR bP ."])
    pending = [make_move("wR", 0, 0, 0, 1, arrive_at=1000)]
    apply_arrived_moves(board, pending, clock=1001)
    assert board[0][1] == "wR"
    assert board[0][0] == "."


def test_apply_with_empty_pending_list():
    board = make_board(["wR . ."])
    remaining = apply_arrived_moves(board, [], clock=5000)
    assert board[0][0] == "wR"
    assert remaining == []


# ---------------------------------------------------------------------------
# handle_click — pending move creation
# ---------------------------------------------------------------------------

def test_click_legal_move_returns_pending_move():
    board = make_board(["wR . ."])
    selected, pending = handle_click(board, [], None, 0, 0, clock=0)
    # first click selects the piece
    assert selected == (0, 0)
    assert pending is None
    selected, pending = handle_click(board, [], selected, 200, 0, clock=0)
    assert pending is not None
    assert pending.piece == "wR"
    assert pending.to_col == 2
    assert pending.arrive_at == MOVE_DURATION_MS


def test_click_legal_move_does_not_mutate_board():
    board = make_board(["wR . ."])
    selected = (0, 0)
    handle_click(board, [], selected, 200, 0, clock=0)
    # board must be unchanged until the move arrives
    assert board[0][0] == "wR"
    assert board[0][2] == "."


def test_click_illegal_move_returns_no_pending_move():
    board = make_board(["wR . ."])
    selected = (0, 0)
    # Rook cannot move diagonally
    selected, pending = handle_click(board, [], selected, 100, 100, clock=0)
    assert pending is None


def test_click_arrive_at_uses_clock_offset():
    board = make_board(["wR . ."])
    selected = (0, 0)
    _, pending = handle_click(board, [], selected, 200, 0, clock=500)
    assert pending.arrive_at == 500 + MOVE_DURATION_MS


# ---------------------------------------------------------------------------
# process_commands — timing integration
# ---------------------------------------------------------------------------

def test_print_board_before_move_arrives_shows_original(capsys):
    board = make_board(["wR . ."])
    # click at t=0, print immediately (clock still 0, move arrives at 1000)
    commands = ["click 0 0", "click 200 0", "print board"]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == "wR . ."


def test_print_board_after_wait_shows_moved_piece(capsys):
    board = make_board(["wR . ."])
    # wait MOVE_DURATION_MS puts clock == arrive_at, piece still in transit.
    # need one extra ms for it to land.
    commands = ["click 0 0", "click 200 0", f"wait {MOVE_DURATION_MS + 1}", "print board"]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == ". . wR"


def test_print_board_partial_wait_still_shows_original(capsys):
    board = make_board(["wR . ."])
    commands = ["click 0 0", "click 200 0", f"wait {MOVE_DURATION_MS - 1}", "print board"]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == "wR . ."


def test_two_prints_before_and_after_arrival(capsys):
    board = make_board(["wR . ."])
    commands = [
        "click 0 0", "click 200 0",
        "print board",
        f"wait {MOVE_DURATION_MS + 1}",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == "wR . ."
    assert lines[1] == ". . wR"


def test_pawn_move_is_deferred(capsys):
    board = make_board([
        ". . .",
        "wP . .",
        ". . .",
    ])
    # white pawn moves forward (row 1 -> row 0), click at pixel (0,100) -> (0,0)
    commands = ["click 0 100", "click 0 0", "print board"]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip().splitlines()
    assert output[0] == ". . ."   # pawn not yet arrived
    assert output[1] == "wP . ."  # pawn still at origin


def test_pawn_arrives_after_wait(capsys):
    board = make_board([
        ". . .",
        "wP . .",
        ". . .",
    ])
    commands = ["click 0 100", "click 0 0", f"wait {MOVE_DURATION_MS + 1}", "print board"]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip().splitlines()
    assert output[0] == "wP . ."
    assert output[1] == ". . ."


# ---------------------------------------------------------------------------
# is_piece_moving
# ---------------------------------------------------------------------------

def test_piece_is_moving_when_pending():
    pending = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    assert is_piece_moving(pending, 0, 0) is True


def test_piece_is_not_moving_when_no_pending():
    assert is_piece_moving([], 0, 0) is False


def test_piece_is_not_moving_when_different_square():
    pending = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    assert is_piece_moving(pending, 0, 1) is False


def test_piece_at_destination_is_not_considered_moving():
    # destination square is not the origin — should not block clicks there
    pending = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    assert is_piece_moving(pending, 0, 2) is False


# ---------------------------------------------------------------------------
# handle_click — cannot select a moving piece
# ---------------------------------------------------------------------------

def test_cannot_select_moving_piece():
    board = make_board(["wR . ."])
    pending = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    # try to select the rook while it is in flight
    selected, new_move = handle_click(board, pending, None, 0, 0, clock=0)
    assert selected is None
    assert new_move is None


def test_can_select_piece_after_arrival():
    board = make_board([". . wR"])
    # move has arrived — pending list is empty
    selected, new_move = handle_click(board, [], None, 200, 0, clock=1001)
    assert selected == (0, 2)
    assert new_move is None


def test_cannot_switch_selection_to_moving_piece():
    board = make_board(["wK wR ."])
    # wR is moving
    pending = [make_move("wR", 0, 1, 0, 2, arrive_at=1000)]
    # select wK first
    selected = (0, 0)
    # try to switch to wR while it is in flight — selection must stay on wK
    new_selected, new_move = handle_click(board, pending, selected, 100, 0, clock=0)
    assert new_selected == (0, 0)
    assert new_move is None


def test_can_switch_selection_to_piece_that_is_not_moving():
    board = make_board(["wK wR ."])
    pending = []
    selected = (0, 0)
    new_selected, _ = handle_click(board, pending, selected, 100, 0, clock=0)
    assert new_selected == (0, 1)


# ---------------------------------------------------------------------------
# process_commands — redirect ignored while in flight
# ---------------------------------------------------------------------------

def test_redirect_ignored_while_piece_is_moving(capsys):
    board = make_board(["wR . . . ."])
    commands = [
        "click 0 0",    # select wR
        "click 400 0",  # move to col 4 — pending, arrive_at=1000
        "click 0 0",    # try to re-select wR while moving — ignored
        "click 300 0",  # try to redirect to col 3 — ignored (nothing selected)
        f"wait {MOVE_DURATION_MS + 1}",
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    # rook must arrive at col 4, not col 3
    assert output == ". . . . wR"


def test_piece_movable_again_immediately_after_arrival(capsys):
    board = make_board(["wR . . . ."])
    commands = [
        "click 0 0",    # select wR
        "click 200 0",  # move to col 2, arrive_at=1000
        f"wait {MOVE_DURATION_MS + 1}",  # piece arrives at col 2
        "click 200 0",  # select wR at its new position
        "click 400 0",  # move to col 4
        f"wait {MOVE_DURATION_MS + 1}",
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == ". . . . wR"


# ---------------------------------------------------------------------------
# handle_click — validation branches not previously covered
#
# These three tests cover the three "return None, None" paths inside
# handle_click that were added when we wired legality checks into the
# deferred-movement flow (iteration 6).  Before that, movement was
# immediate and the same checks lived in a different call path.
# ---------------------------------------------------------------------------

def test_illegal_move_for_non_pawn_returns_no_pending():
    # Rook at (0,0) trying to move diagonally — is_legal_move returns False.
    # Covers the branch: non-pawn, is_legal_move fails → return None, None
    board = make_board(["wR . .", ". . .", ". . ."])
    selected = (0, 0)
    new_selected, pending = handle_click(board, [], selected, 100, 100, clock=0)
    assert new_selected is None
    assert pending is None


def test_blocked_path_for_sliding_piece_returns_no_pending():
    # Rook at (0,0) wants to reach (0,2) but (0,1) is occupied.
    # Covers the branch: sliding piece, is_path_clear fails → return None, None
    board = make_board(["wR bP ."])
    selected = (0, 0)
    new_selected, pending = handle_click(board, [], selected, 200, 0, clock=0)
    assert new_selected is None
    assert pending is None


def test_illegal_pawn_move_returns_no_pending():
    # White pawn at (1,0) trying to move sideways — is_legal_pawn_move returns False.
    # Covers the branch: pawn, is_legal_pawn_move fails → return None, None
    board = make_board([". . .", "wP . .", ". . ."])
    selected = (1, 0)
    # click on (1,1) — same row, pawn cannot move sideways
    new_selected, pending = handle_click(board, [], selected, 100, 100, clock=0)
    assert new_selected is None
    assert pending is None
