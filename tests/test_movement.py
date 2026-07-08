import pytest
from game.movement import PendingMove, apply_arrived_moves
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
    board = make_board(["wR . ."])
    pending = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    remaining = apply_arrived_moves(board, pending, clock=1000)
    assert board[0][2] == "wR"
    assert board[0][0] == "."
    assert len(remaining) == 0


def test_move_arrives_after_time():
    board = make_board(["wR . ."])
    pending = [make_move("wR", 0, 0, 0, 2, arrive_at=1000)]
    remaining = apply_arrived_moves(board, pending, clock=1500)
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
    # wR has arrived
    assert board[0][1] == "wR"
    assert board[0][0] == "."
    # wB has not arrived yet
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
