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


def test_move_arrives_exactly_at_time():
    # arrive_at is inclusive: the piece lands exactly when clock == arrive_at
    board = make_board(["wR . ."])
    pending = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    remaining = apply_arrived_moves(board, pending, clock=1000)
    assert board[0][2] == "wR"
    assert board[0][0] == "."
    assert len(remaining) == 0


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
    remaining = apply_arrived_moves(board, pending, clock=1000)
    assert board[0][2] == "wR"
    assert board[1][2] == "wB"
    assert len(remaining) == 0


def test_arrived_move_captures_enemy():
    board = make_board(["wR bP ."])
    pending = [make_move("wR", 0, 0, 0, 1, arrive_at=1000)]
    apply_arrived_moves(board, pending, clock=1000)
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
    commands = ["click 0 0", "click 200 0", f"wait {MOVE_DURATION_MS}", "print board"]
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
        f"wait {MOVE_DURATION_MS}",
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
    commands = ["click 0 100", "click 0 0", f"wait {MOVE_DURATION_MS}", "print board"]
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
        "click 0 0",
        "click 400 0",  # move to col 4, arrive_at=1000
        "click 0 0",    # try to re-select wR while moving — ignored
        "click 300 0",  # try to redirect to col 3 — ignored (nothing selected)
        f"wait {MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == ". . . . wR"


def test_piece_movable_again_immediately_after_arrival(capsys):
    board = make_board(["wR . . . ."])
    commands = [
        "click 0 0",
        "click 200 0",  # move to col 2, arrive_at=1000
        f"wait {MOVE_DURATION_MS}",  # piece arrives at col 2
        "click 200 0",  # select wR at its new position
        "click 400 0",  # move to col 4
        f"wait {MOVE_DURATION_MS}",
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


# ---------------------------------------------------------------------------
# opposite-color concurrency rule (platform tests 1–4)
# ---------------------------------------------------------------------------

def test_opposite_color_cannot_start_while_other_color_is_moving(capsys):
    # wR starts moving at t=0; bR click while wR is in flight must be ignored.
    # After wait 2000 both would normally arrive, but bR never started.
    board = make_board([
        "wR . .",
        ". . .",
        "bR . .",
    ])
    commands = [
        "click 50 50",    # select wR  (pixel → row=0, col=0)
        "click 250 50",   # wR → col 2, arrive_at=1000
        "click 50 250",   # try to select bR — ignored (opposite color in flight)
        "click 250 250",  # try to send bR — ignored (nothing selected)
        f"wait 2000",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == ". . wR"   # wR arrived
    assert lines[2] == "bR . ."   # bR never moved


def test_opposite_color_can_move_after_first_arrives(capsys):
    # wR arrives at t=1000; after that bR should be free to move.
    board = make_board([
        "wR . .",
        ". . .",
        "bR . .",
    ])
    commands = [
        "click 50 50",    # select wR
        "click 250 50",   # wR → col 2, arrive_at=1000
        f"wait {MOVE_DURATION_MS}",   # wR lands, pending list now empty
        "click 50 250",   # select bR — now allowed
        "click 250 250",  # bR → col 2, arrive_at=2000
        f"wait {MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == ". . wR"
    assert lines[2] == ". . bR"


def test_same_color_can_move_concurrently(capsys):
    # Two white pieces may have pending moves at the same time.
    board = make_board([
        "wR . wN . .",
    ])
    commands = [
        "click 0 0",     # select wR  (col=0)
        "click 100 0",   # wR → col 1
        "click 200 0",   # select wN  (col=2) — same color, allowed
        "click 400 0",   # wN knight move: row=0,col=2 → row=0? no — use row move
        # Knight from (0,2): valid L-shape e.g. to (1,3) but board is 1 row.
        # Use two rooks instead to keep it simple.
    ]
    # simpler: two rooks on a 2-row board
    board2 = make_board([
        "wR . . . .",
        "wR . . . .",
    ])
    commands2 = [
        "click 0 0",     # select wR row=0,col=0
        "click 400 0",   # wR row=0 → col=4
        "click 0 100",   # select wR row=1,col=0 — same color, allowed
        "click 400 100", # wR row=1 → col=4
        f"wait {MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board2, commands2)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == ". . . . wR"
    assert lines[1] == ". . . . wR"


def test_no_cooldown_after_arrival(capsys):
    # Immediately after wR arrives, the same piece can move again.
    board = make_board(["wR . ."])
    commands = [
        "click 50 50",    # select wR
        "click 150 50",   # wR → col 1, arrive_at=1000
        f"wait {MOVE_DURATION_MS}",   # wR lands at col 1
        "click 150 50",   # select wR at col 1 — no cooldown
        "click 250 50",   # wR → col 2
        f"wait {MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == ". . wR"
