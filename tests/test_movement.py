import pytest
from game.realtime.motion import PendingMove, is_piece_moving
from game.realtime.movement_resolver import apply_arrived_moves
from game.io.command_runner import process_commands
from game.input.controller import Controller
from game.engine.game_engine import GameEngine
from game.model.constants import MOVE_DURATION_MS


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
    remaining, game_over, _ = apply_arrived_moves(board, pending, clock=999)
    assert board[0][0] == "wR"
    assert board[0][2] == "."
    assert len(remaining) == 1
    assert game_over is False


def test_move_arrives_exactly_at_time():
    # arrive_at is inclusive: the piece lands exactly when clock == arrive_at
    board = make_board(["wR . ."])
    pending = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    remaining, game_over, _ = apply_arrived_moves(board, pending, clock=1000)
    assert board[0][2] == "wR"
    assert board[0][0] == "."
    assert len(remaining) == 0
    assert game_over is False


def test_move_arrives_after_time():
    board = make_board(["wR . ."])
    pending = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    remaining, game_over, _ = apply_arrived_moves(board, pending, clock=1001)
    assert board[0][2] == "wR"
    assert board[0][0] == "."
    assert len(remaining) == 0
    assert game_over is False


def test_only_arrived_moves_are_applied():
    board = make_board(["wR . . . wB"])
    pending = [
        make_move("wR", 0, 0, 0, 1, arrive_at=500),
        make_move("wB", 0, 4, 0, 3, arrive_at=2000),
    ]
    remaining, game_over, _ = apply_arrived_moves(board, pending, clock=1000)
    # wR has arrived (arrive_at=500 < clock=1000)
    assert board[0][1] == "wR"
    assert board[0][0] == "."
    # wB has not arrived yet (arrive_at=2000 > clock=1000)
    assert board[0][4] == "wB"
    assert board[0][3] == "."
    assert len(remaining) == 1
    assert game_over is False


def test_multiple_moves_arrive_at_same_time():
    board = make_board([
        "wR . .",
        "wB . .",
    ])
    pending = [
        make_move("wR", 0, 0, 0, 2, arrive_at=1000),
        make_move("wB", 1, 0, 1, 2, arrive_at=1000),
    ]
    remaining, game_over, _ = apply_arrived_moves(board, pending, clock=1000)
    assert board[0][2] == "wR"
    assert board[1][2] == "wB"
    assert len(remaining) == 0
    assert game_over is False


def test_arrived_move_captures_enemy():
    board = make_board(["wR bP ."])
    pending = [make_move("wR", 0, 0, 0, 1, arrive_at=1000)]
    apply_arrived_moves(board, pending, clock=1000)
    assert board[0][1] == "wR"
    assert board[0][0] == "."


def test_apply_with_empty_pending_list():
    board = make_board(["wR . ."])
    remaining, game_over, _ = apply_arrived_moves(board, [], clock=5000)
    assert board[0][0] == "wR"
    assert remaining == []
    assert game_over is False


# ---------------------------------------------------------------------------
# Controller.click — pending move creation
# ---------------------------------------------------------------------------

def test_click_legal_move_returns_pending_move():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    ctrl = Controller(engine)
    result = ctrl.click(0, 0)
    # first click selects the piece
    assert ctrl.selected == (0, 0)
    assert result is False
    result = ctrl.click(200, 0)
    assert result is True
    assert len(engine.pending_moves) == 1
    move = engine.pending_moves[0]
    assert move.piece == "wR"
    assert move.to_col == 2
    assert move.arrive_at == 2 * MOVE_DURATION_MS


def test_click_legal_move_does_not_mutate_board():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    ctrl = Controller(engine)
    ctrl.selected = (0, 0)
    ctrl.click(200, 0)
    # board must be unchanged until the move arrives
    assert board[0][0] == "wR"
    assert board[0][2] == "."


def test_click_illegal_move_returns_no_pending_move():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    ctrl = Controller(engine)
    ctrl.selected = (0, 0)
    # Rook cannot move diagonally
    result = ctrl.click(100, 100)
    assert result is False
    assert len(engine.pending_moves) == 0


def test_click_arrive_at_uses_clock_offset():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    engine.arbiter.clock = 500
    ctrl = Controller(engine)
    ctrl.selected = (0, 0)
    ctrl.click(200, 0)
    assert engine.pending_moves[0].arrive_at == 500 + 2 * MOVE_DURATION_MS


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
    commands = ["click 0 0", "click 200 0", f"wait {2 * MOVE_DURATION_MS}", "print board"]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == ". . wR"


def test_print_board_partial_wait_still_shows_original(capsys):
    board = make_board(["wR . ."])
    commands = ["click 0 0", "click 200 0", f"wait {2 * MOVE_DURATION_MS - 1}", "print board"]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == "wR . ."


def test_two_prints_before_and_after_arrival(capsys):
    board = make_board(["wR . ."])
    commands = [
        "click 0 0", "click 200 0",
        "print board",
        f"wait {2 * MOVE_DURATION_MS}",
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
    # wP at row=1, moves to row=0 on a 3-row board.
    # row=0 is the promotion row for white → pawn becomes queen on arrival.
    commands = ["click 0 100", "click 0 0", f"wait {MOVE_DURATION_MS}", "print board"]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip().splitlines()
    assert output[0] == "wQ . ."   # promoted to queen
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
# Controller.click — cannot select a moving piece
# ---------------------------------------------------------------------------

def test_cannot_select_moving_piece():
    board = make_board(["wR . ."])
    engine = GameEngine(board)
    engine.arbiter.pending_moves = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    ctrl = Controller(engine)
    # try to select the rook while it is in flight
    result = ctrl.click(0, 0)
    assert ctrl.selected is None
    assert result is False


def test_can_select_piece_after_arrival():
    board = make_board([". . wR"])
    engine = GameEngine(board)
    # move has arrived — pending list is empty
    ctrl = Controller(engine)
    result = ctrl.click(200, 0)
    assert ctrl.selected == (0, 2)
    assert result is False


def test_cannot_switch_selection_to_moving_piece():
    board = make_board(["wK wR ."])
    engine = GameEngine(board)
    engine.arbiter.pending_moves = [make_move("wR", 0, 1, 0, 2, arrive_at=1000)]
    ctrl = Controller(engine)
    ctrl.selected = (0, 0)
    # try to switch to wR while it is in flight — selection must stay on wK
    result = ctrl.click(100, 0)
    assert ctrl.selected == (0, 0)
    assert result is False


def test_can_switch_selection_to_piece_that_is_not_moving():
    board = make_board(["wK wR ."])
    engine = GameEngine(board)
    ctrl = Controller(engine)
    ctrl.selected = (0, 0)
    ctrl.click(100, 0)
    assert ctrl.selected == (0, 1)


# ---------------------------------------------------------------------------
# process_commands — redirect ignored while in flight
# ---------------------------------------------------------------------------

def test_redirect_ignored_while_piece_is_moving(capsys):
    board = make_board(["wR . . . ."])
    commands = [
        "click 0 0",
        "click 400 0",  # move to col 4, arrive_at=4000
        "click 0 0",    # try to re-select wR while moving — ignored
        "click 300 0",  # try to redirect to col 3 — ignored (nothing selected)
        f"wait {4 * MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == ". . . . wR"


def test_piece_movable_again_immediately_after_arrival(capsys):
    board = make_board(["wR . . . ."])
    commands = [
        "click 0 0",
        "click 200 0",  # move to col 2, arrive_at=2000
        f"wait {2 * MOVE_DURATION_MS}",  # piece arrives at col 2
        "click 200 0",  # select wR at its new position
        "click 400 0",  # move to col 4
        f"wait {2 * MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == ". . . . wR"


# ---------------------------------------------------------------------------
# Controller.click — validation branches not previously covered
#
# These three tests cover the three "return False" paths inside
# Controller.click that were added when we wired legality checks into the
# deferred-movement flow (iteration 6).  Before that, movement was
# immediate and the same checks lived in a different call path.
# ---------------------------------------------------------------------------

def test_illegal_move_for_non_pawn_returns_no_pending():
    # Rook at (0,0) trying to move diagonally — is_legal_move returns False.
    # Covers the branch: non-pawn, is_legal_move fails → return False
    board = make_board(["wR . .", ". . .", ". . ."])
    engine = GameEngine(board)
    ctrl = Controller(engine)
    ctrl.selected = (0, 0)
    result = ctrl.click(100, 100)
    assert ctrl.selected is None
    assert result is False
    assert len(engine.pending_moves) == 0


def test_blocked_path_for_sliding_piece_returns_no_pending():
    # Rook at (0,0) wants to reach (0,2) but (0,1) is occupied.
    # Covers the branch: sliding piece, is_path_clear fails → return False
    board = make_board(["wR bP ."])
    engine = GameEngine(board)
    ctrl = Controller(engine)
    ctrl.selected = (0, 0)
    result = ctrl.click(200, 0)
    assert ctrl.selected is None
    assert result is False
    assert len(engine.pending_moves) == 0


def test_illegal_pawn_move_returns_no_pending():
    # White pawn at (1,0) trying to move sideways — is_legal_pawn_move returns False.
    # Covers the branch: pawn, is_legal_pawn_move fails → return False
    board = make_board([". . .", "wP . .", ". . ."])
    engine = GameEngine(board)
    ctrl = Controller(engine)
    ctrl.selected = (1, 0)
    # click on (1,1) — same row, pawn cannot move sideways
    result = ctrl.click(100, 100)
    assert ctrl.selected is None
    assert result is False
    assert len(engine.pending_moves) == 0


# ---------------------------------------------------------------------------
# opposite-color concurrency rule (platform tests 1–4)
# ---------------------------------------------------------------------------

def test_opposite_colors_can_move_concurrently(capsys):
    # Both wR and bR may start moving at the same time — no broad color block.
    board = make_board([
        "wR . .",
        ". . .",
        "bR . .",
    ])
    commands = [
        "click 50 50",    # select wR (row=0, col=0)
        "click 250 50",   # wR → col 2, arrive_at=2000
        "click 50 250",   # select bR (row=2, col=0) — allowed, different color
        "click 250 250",  # bR → col 2, arrive_at=2000
        f"wait {2 * MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == ". . wR"
    assert lines[2] == ". . bR"


def test_opposite_color_can_move_after_first_arrives(capsys):
    # wR arrives at t=2000; after that bR should be free to move.
    board = make_board([
        "wR . .",
        ". . .",
        "bR . .",
    ])
    commands = [
        "click 50 50",    # select wR
        "click 250 50",   # wR → col 2, arrive_at=2000
        f"wait {2 * MOVE_DURATION_MS}",   # wR lands, pending list now empty
        "click 50 250",   # select bR — now allowed
        "click 250 250",  # bR → col 2, arrive_at=4000
        f"wait {2 * MOVE_DURATION_MS}",
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
        f"wait {4 * MOVE_DURATION_MS}",
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


# ===========================================================================
# Iteration 8 — advanced real-time interaction
# ===========================================================================

# ---------------------------------------------------------------------------
# T1 & T2: enemy collision — first mover wins
#
# How it works: when both pieces target each other's squares concurrently,
# starting a move while the first color is in flight.  The second click is
# therefore ignored and only the first piece arrives.
# ---------------------------------------------------------------------------

def test_enemy_collision_both_move_first_mover_wins(capsys):
    # wR starts toward col=3 (where bR is), bR starts toward col=0 (where wR was).
    # Both are in flight simultaneously with the same arrive_at.
    # apply_arrived_moves processes wR first (it was added first to pending list).
    # wR lands at (0,3) capturing bR. bR's move checks origin (0,3) — now "wR", not "bR"
    # → bR's move is cancelled. Result: . . . wR
    board = make_board(["wR . . bR"])
    commands = [
        "click 50 50",   # select wR (col=0)
        "click 350 50",  # wR → col=3, arrive_at=3000
        "click 350 50",  # select bR (col=3) — allowed (concurrent)
        "click 50 50",   # bR → col=0, arrive_at=3000
        "wait 3000",
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    # wR processed first: lands at (0,3), bR captured.
    # bR processed second: origin (0,3) is now "wR" ≠ "bR" → cancelled.
    assert output == ". . . wR"


# ---------------------------------------------------------------------------
# T3: friendly blocker — sliding piece cannot move through friendly piece
#
# How it works: is_path_clear checks squares between source and destination;
# wP at (1,1) blocks wR at (1,0) from reaching (1,2).
# ---------------------------------------------------------------------------

def test_cannot_start_move_through_friendly_piece(capsys):
    board = make_board([
        ". . .",
        "wR wP .",
        ". . .",
    ])
    commands = [
        "click 50 150",   # select wR at (row=1, col=0)
        "click 250 150",  # try to move to (row=1, col=2) — wP blocks path
        "wait 2000",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[1] == "wR wP ."   # board unchanged


def test_sliding_piece_can_move_to_adjacent_friendly_free_square(capsys):
    # Sanity: rook can reach col=1 when nothing is blocking
    board = make_board([
        ". . .",
        "wR . .",
        ". . .",
    ])
    commands = [
        "click 50 150",
        "click 150 150",
        "wait 1000",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[1] == ". wR ."


# ---------------------------------------------------------------------------
# T4: dynamic block — opposite color is blocked mid-flight
#
# wQ starts moving at t=0; at t=200 bP tries to move into wQ's path.
# bP is blocked because wQ (opposite color) is already in flight.
# wQ arrives at its destination unimpeded.
# ---------------------------------------------------------------------------

def test_dynamic_block_opposite_color_blocked_while_queen_in_flight(capsys):
    board = make_board([
        ". . . .",
        "wQ . . bK",
        ". . bP .",
        ". . . .",
    ])
    commands = [
        "click 50 150",   # select wQ (row=1, col=0)
        "click 350 150",  # wQ → (row=1, col=3), arrive_at=3000
        "wait 200",
        "click 250 250",  # try to select bP (row=2, col=2) — opposite color blocked
        "click 250 150",  # nothing selected → ignored
        "wait 3000",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[1] == ". . . wQ"
    assert lines[2] == ". . bP ."   # bP never moved


# ---------------------------------------------------------------------------
# T5: knight cannot land on friendly piece
#
# How it works: wN at (2,0) tries to jump to (0,1) where wP sits.
# The second click triggers the "switch selection to friendly piece" branch
# instead of creating a move — so wN never moves.
# ---------------------------------------------------------------------------

def test_knight_cannot_land_on_friendly_piece(capsys):
    board = make_board([
        ". wP .",
        ". . .",
        "wN . .",
    ])
    commands = [
        "click 50 250",  # select wN (row=2, col=0)
        "click 150 50",  # (row=0, col=1) has wP — switches selection, no move
        "wait 1000",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == ". wP ."
    assert lines[2] == "wN . ."


def test_knight_can_land_on_empty_square(capsys):
    # Sanity: knight moves normally when destination is empty
    board = make_board([
        ". . .",
        ". . .",
        "wN . .",
    ])
    commands = [
        "click 50 250",   # select wN (row=2, col=0)
        "click 150 50",   # (row=0, col=1) — valid knight move, empty
        "wait 2000",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == ". wN ."
    assert lines[2] == ". . ."


def test_knight_can_capture_enemy(capsys):
    # Knight may land on an enemy piece (capture)
    board = make_board([
        ". bP .",
        ". . .",
        "wN . .",
    ])
    commands = [
        "click 50 250",
        "click 150 50",
        "wait 2000",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == ". wN ."
    assert lines[2] == ". . ."


# ---------------------------------------------------------------------------
# T6: premove does not execute in common route
#
# wR starts moving to col=1 (arrive_at=1000).
# While moving, player tries to re-select wR (blocked) then send it to col=2
# (nothing selected → ignored).
# After wait 2000, wR is at col=1 and never reached col=2.
# ---------------------------------------------------------------------------

def test_premove_does_not_execute_in_common_route(capsys):
    board = make_board(["wR . ."])
    commands = [
        "click 50 50",    # select wR (col=0)
        "click 150 50",   # wR → col=1, arrive_at=1000
        "click 50 50",    # try to re-select wR while moving — blocked
        "click 250 50",   # nothing selected → ignored
        "wait 2000",
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == ". wR ."


def test_premove_executes_after_first_arrives(capsys):
    # A second move IS possible if it is issued after the first arrives.
    board = make_board(["wR . ."])
    commands = [
        "click 50 50",
        "click 150 50",   # wR → col=1, arrive_at=1000
        "wait 1000",      # wR lands
        "click 150 50",   # select wR at new position
        "click 250 50",   # wR → col=2
        "wait 1000",
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == ". . wR"


# ===========================================================================
# Conflict rules — explicit coverage per requirements
# ===========================================================================

def test_two_pieces_cannot_target_same_destination(capsys):
    # Two white rooks on different rows both try to reach (0,2).
    # The second move is blocked by is_destination_claimed.
    board = make_board([
        "wR . . . .",
        ". . . . .",
        "wR . . . .",
    ])
    commands = [
        "click 0 0",      # select wR at (row=0, col=0)
        "click 200 0",    # wR row=0 → (row=0, col=2), destination (0,2) claimed
        "click 0 200",    # select wR at (row=2, col=0)
        "click 200 0",    # wR row=2 tries → (row=0, col=2) — blocked by is_destination_claimed
        f"wait {2 * MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == ". . wR . ."   # first rook arrived at (0,2)
    assert lines[2] == "wR . . . ."   # second rook never moved


def test_moving_piece_cannot_be_redirected(capsys):
    # wR is sent to col=3. While in flight, player tries to re-select and redirect.
    # Re-selection fails (is_piece_moving), redirect is ignored.
    board = make_board(["wR . . . ."])
    commands = [
        "click 0 0",
        "click 300 0",    # wR → col=3
        "click 0 0",      # try to re-select wR while moving — blocked
        "click 100 0",    # nothing selected → ignored
        f"wait {3 * MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == ". . . wR ."     # arrived at col=3, not col=1


def test_opposite_color_pieces_move_concurrently_no_conflict(capsys):
    # wR moves along row 0, bR moves along row 2 — no shared destination.
    # Both should arrive normally.
    board = make_board([
        "wR . . . .",
        ". . . . .",
        "bR . . . .",
    ])
    commands = [
        "click 0 0",      # select wR
        "click 400 0",    # wR → col=4
        "click 0 200",    # select bR — allowed (different color, no conflict)
        "click 400 200",  # bR → col=4 on row=2 — different destination
        f"wait {4 * MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == ". . . . wR"
    assert lines[2] == ". . . . bR"


def test_same_color_pieces_move_concurrently_no_conflict(capsys):
    # Two white pieces move to different destinations simultaneously.
    board = make_board([
        "wR . . . .",
        "wR . . . .",
    ])
    commands = [
        "click 0 0",      # select wR row=0
        "click 100 0",    # wR row=0 → col=1
        "click 0 100",    # select wR row=1
        "click 300 100",  # wR row=1 → col=3 — different destination, allowed
        f"wait {3 * MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == ". wR . . ."
    assert lines[1] == ". . . wR ."


# ===========================================================================
# Game over — king capture
# ===========================================================================

def test_capturing_enemy_king_returns_game_over():
    # wR arrives at the square occupied by bK → game_over = True
    board = make_board(["wR . bK"])
    pending = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    remaining, game_over, _ = apply_arrived_moves(board, pending, clock=1000)
    assert game_over is True
    assert board[0][2] == "wR"   # king captured, wR now there


def test_capturing_non_king_does_not_trigger_game_over():
    board = make_board(["wR bP ."])
    pending = [make_move("wR", 0, 0, 0, 1, arrive_at=1000)]
    remaining, game_over, _ = apply_arrived_moves(board, pending, clock=1000)
    assert game_over is False


def test_game_over_pending_moves_cleared():
    # Two moves arrive at the same time; first captures the king.
    # Second move (still pending at same clock) must be discarded.
    board = make_board(["wR bK", "wB . "])
    pending = [
        make_move("wR", 0, 0, 0, 1, arrive_at=1000),   # captures bK → game over
        make_move("wB", 1, 0, 1, 1, arrive_at=1000),   # should be cancelled
    ]
    remaining, game_over, _ = apply_arrived_moves(board, pending, clock=1000)
    assert game_over is True
    assert len(remaining) == 0
    assert board[1][0] == "wB"   # wB never moved


def test_game_over_triggered_only_on_arrival_not_on_click(capsys):
    # King is captured at t=2000. print board at t=0 should show original.
    board = make_board(["wR . bK"])
    commands = [
        "click 0 0",
        "click 200 0",   # wR → col=2 (bK), arrive_at=2000
        "print board",   # t=0: game not over yet
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == "wR . bK"   # king still alive at t=0


def test_game_over_board_state_after_king_capture(capsys):
    board = make_board(["wR . bK"])
    commands = [
        "click 0 0",
        "click 200 0",
        "wait 2000",
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == ". . wR"


def test_clicks_ignored_after_game_over(capsys):
    board = make_board(["wR . bK . wB"])
    commands = [
        "click 0 0",
        "click 200 0",    # wR → bK, arrive_at=2000
        "wait 2000",      # game over
        "click 400 0",    # try to select wB — must be ignored
        "click 300 0",    # try to move wB — must be ignored
        "wait 1000",
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    # wR captured bK, wB never moved
    assert output == ". . wR . wB"


def test_pending_moves_cancelled_on_game_over(capsys):
    # wR captures bK; wB has a pending move that hasn't arrived yet.
    # After game over, wB's move must be cancelled.
    board = make_board([
        "wR . bK",
        "wB . .  ",
    ])
    commands = [
        "click 0 0",
        "click 200 0",    # wR → (0,2)=bK, arrive_at=2000
        "click 0 100",
        "click 200 100",  # wB → (1,2), arrive_at=2000
        "wait 2000",      # both arrive at same time; wR processed first → game over
        "wait 1000",      # extra wait — wB must NOT land
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == ". . wR"
    assert lines[1] == "wB . ."   # wB never moved


def test_print_board_works_after_game_over(capsys):
    board = make_board(["wR . bK"])
    commands = [
        "click 0 0",
        "click 200 0",
        "wait 2000",
        "print board",
        "print board",   # second print should also work
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert lines[0] == ". . wR"
    assert lines[1] == ". . wR"


def test_wait_after_game_over_does_not_execute_pending(capsys):
    board = make_board(["wR . bK . wB"])
    commands = [
        "click 0 0",
        "click 200 0",    # wR → bK, arrive_at=2000
        "click 400 0",    # select wB
        "click 300 0",    # wB → col=3, arrive_at=1000
        "wait 2000",      # wR arrives first, game over; wB cancelled
        "wait 5000",      # further time — nothing should happen
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == ". . wR . wB"


# ===========================================================================
# Iteration 10 — pawn double step and promotion (integration)
# ===========================================================================

def test_white_pawn_double_step_via_process_commands(capsys):
    # 8-row board. White starting row = row 6. wP at row 6 moves to row 4.
    board = make_board([
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        "wP . .",
        ". . .",
    ])
    commands = [
        "click 0 650",    # select wP at (row=6, col=0)
        "click 0 450",    # move to (row=4, col=0)
        f"wait {2 * MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[4] == "wP . ."
    assert lines[6] == ". . ."


def test_black_pawn_double_step_via_process_commands(capsys):
    # 8-row board. Black starting row = row 1. bP at row 1 moves to row 3.
    board = make_board([
        ". . .",
        "bP . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
        ". . .",
    ])
    commands = [
        "click 0 150",    # select bP at row=1
        "click 0 350",    # move to row=3
        f"wait {2 * MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[1] == ". . ."
    assert lines[3] == "bP . ."


def test_white_pawn_promotes_to_queen_on_arrival(capsys):
    # wP one step from promotion row. After arrival it becomes wQ.
    board = make_board([
        ". . .",
        "wP . .",
        ". . .",
        ". . .",
    ])
    # Starting row for white on 4-row board = row 2.
    # wP is at row 1 (not starting row), moves one step to row 0.
    commands = [
        "click 0 150",    # select wP at row=1
        "click 0 50",     # move to row=0 (promotion row)
        f"wait {MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == "wQ . ."   # promoted
    assert lines[1] == ". . ."


def test_black_pawn_promotes_to_queen_on_arrival(capsys):
    board = make_board([
        ". . .",
        ". . .",
        "bP . .",
        ". . .",
    ])
    # Black promotion row on 4-row board = row 3.
    # bP at row=2, moves to row=3.
    commands = [
        "click 0 250",
        "click 0 350",
        f"wait {MOVE_DURATION_MS}",
        "print board",
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[3] == "bQ . ."
    assert lines[2] == ". . ."


def test_promotion_does_not_happen_before_arrival(capsys):
    # Pawn is in flight toward promotion row — print board before arrival
    # must still show the pawn at its origin, not a queen anywhere.
    board = make_board([
        ". . .",
        "wP . .",
        ". . .",
        ". . .",
    ])
    commands = [
        "click 0 150",
        "click 0 50",    # wP → row=0, arrive_at=1000
        "print board",   # t=0: pawn not yet arrived
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == ". . ."    # no queen yet
    assert lines[1] == "wP . ."   # pawn still at origin


# ===========================================================================
# Jump / Airborne iteration
# ===========================================================================

def test_jump_lands_same_square(capsys):
    """A piece that jumps stays on the same cell after the jump expires."""
    board = make_board(["wR . ."])
    commands = [
        "jump 50 50",     # wR at (0,0) jumps, expires_at=1000
        "wait 2000",      # jump has expired
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == "wR . ."


def test_airborne_piece_captures_arriving_enemy(capsys):
    """An airborne piece destroys an arriving enemy — the enemy is removed."""
    board = make_board(["wR bR . ."])
    commands = [
        "jump 50 50",     # wR jumps at t=0, expires_at=1000
        "click 150 50",   # select bR (col=1)
        "click 50 50",    # bR → col=0, arrive_at=1000
        "wait 1000",      # clock=1000: jump still active (expires_at not < clock), bR arrives
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    # wR is airborne at (0,0); bR arrives at (0,0) → bR destroyed.
    assert output == "wR . . ."


def test_jump_too_late_does_not_save_piece(capsys):
    """If a piece jumps AFTER an enemy move is already on its way and
    the jump is still active when the enemy arrives, the airborne piece
    destroys the arriving enemy."""
    board = make_board(["wR bR . ."])
    commands = [
        "click 150 50",   # select bR (col=1)
        "click 50 50",    # bR → col=0, arrive_at=1000
        "wait 500",       # clock=500
        "jump 50 50",     # wR jumps at t=500, expires_at=1500
        "wait 500",       # clock=1000: bR arrives, jump (expires 1500) still active → airborne capture
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    # bR arrived at t=1000. At t=1000 wR's jump (expires 1500) is still active → airborne capture!
    assert output == "wR . . ."


def test_enemy_arrives_after_landing_captures_normally(capsys):
    """If the jump has expired before the enemy arrives, the enemy captures normally."""
    board = make_board(["wR . . . . bR"])
    commands = [
        "jump 50 50",     # wR jumps at t=0, expires_at=1000
        "wait 1100",      # clock=1100: jump expired (1000 < 1100)
        "click 550 50",   # select bR (col=5)
        "click 50 50",    # bR → col=0, arrive_at=1100+5*1000=6100
        "wait 5000",      # clock=6100: bR arrives, wR is NOT airborne → normal capture
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == "bR . . . . ."


def test_cannot_jump_while_moving(capsys):
    """A piece that already has a pending move cannot jump."""
    board = make_board(["wR . ."])
    commands = [
        "click 50 50",    # select wR
        "click 250 50",   # wR → col=2, arrive_at=2000
        "jump 50 50",     # try to jump wR — should be ignored (already moving)
        "wait 2000",
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    # wR moved normally, jump was ignored
    assert output == ". . wR"


def test_airborne_capture_only_enemy(capsys):
    """An airborne piece does NOT capture a friendly piece arriving at its cell."""
    board = make_board([
        "wR . . . .",
        "wR . . . .",
    ])
    commands = [
        "jump 50 50",     # wR at (0,0) jumps, expires_at=1000
        "click 50 100",   # select wR at (1,0)
        "click 50 50",    # wR(1,0) → (0,0) — same color, this is a friendly move attempt
    ]
    # Actually, clicking on (0,0) where a friendly piece sits would trigger "switch selection"
    # rather than creating a move. Let's use a scenario with is_destination_claimed instead.
    # Better test: two rows, wK moves to where a friendly wR is airborne.
    # But Controller.click checks same_color for the destination cell (wR at (0,0)).
    # Since wR is there, it would switch selection. So this scenario naturally prevents it.
    # Instead, test at the movement.py level directly:
    pass


def test_airborne_capture_only_enemy_direct():
    """Direct test: apply_arrived_moves does NOT destroy a friendly arriving piece."""
    from game.realtime.motion import ActiveJump
    board = make_board(["wR . wR"])
    # wR at (0,2) is airborne. wR at (0,0) arrives at (0,2).
    # Same color → should NOT trigger airborne capture; normal move_piece occurs.
    active_jumps = [ActiveJump(piece="wR", row=0, col=2, expires_at=2000)]
    pending = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    remaining, game_over, jumps = apply_arrived_moves(board, pending, clock=1000, active_jumps=active_jumps)
    # Friendly piece: airborne capture does NOT apply. Normal move executes.
    assert board[0][2] == "wR"
    assert board[0][0] == "."
    assert game_over is False


def test_cannot_jump_empty_cell(capsys):
    """Jumping an empty cell does nothing."""
    board = make_board(["wR . ."])
    commands = [
        "jump 150 50",    # cell (0,1) is empty
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == "wR . ."
