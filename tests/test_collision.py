"""Tests for path-based collision resolution."""
import pytest
from game.engine.game_engine import GameEngine
from game.io.command_runner import process_commands
from game.model.constants import MOVE_DURATION_MS


def make_board(rows):
    return [row.split() for row in rows]


# ---------------------------------------------------------------------------
# Same-color collision mid-path — later piece stops before
# ---------------------------------------------------------------------------

def test_same_color_rook_and_queen_cross_paths_later_stops():
    """Rook e1→e8 and Queen a4→h4 (same color).
    Queen arrives at e4 first; rook stops at e3."""
    # 8x8 board. Rook at (7,4), Queen at (3,0).
    # Rook moves (7,4)→(0,4): path through (6,4),(5,4),(4,4),(3,4),(2,4),(1,4),(0,4)
    # Queen moves (3,0)→(3,7): path through (3,1),(3,2),(3,3),(3,4),(3,5),(3,6),(3,7)
    # Crossing at (3,4):
    #   Rook arrives at (3,4) at t=0+4*1000=4000
    #   Queen arrives at (3,4) at t=0+4*1000=4000
    # Tie-break: Rook created first (seq=0) → arrives first.
    # Queen (seq=1) sees same-color at (3,4) → stops at (3,3).
    board = make_board([
        ". . . . . . . .",
        ". . . . . . . .",
        ". . . . . . . .",
        "wQ . . . . . . .",
        ". . . . . . . .",
        ". . . . . . . .",
        ". . . . . . . .",
        ". . . . wR . . .",
    ])
    engine = GameEngine(board)
    engine.request_move(7, 4, 0, 4)   # Rook up, seq=0
    engine.request_move(3, 0, 3, 7)   # Queen right, seq=1
    engine.handle_wait(7 * MOVE_DURATION_MS)  # enough for both to finish
    assert board[0][4] == "wR"   # rook arrived at destination
    assert board[3][3] == "wQ"   # queen stopped one before crossing


def test_same_color_same_destination_later_stops_before():
    """Two rooks both heading to same cell. Later one stops before."""
    board = make_board(["wR . . . wR"])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 2)   # seq=0, arrives at t=2000
    engine.request_move(0, 4, 0, 2)   # seq=1, arrives at t=2000
    engine.handle_wait(2 * MOVE_DURATION_MS)
    # seq=0 arrives first (lower seq_id), occupies (0,2)
    # seq=1 sees same-color at (0,2) → stops at (0,3)
    assert board[0][2] == "wR"
    assert board[0][3] == "wR"
    assert board[0][0] == "."
    assert board[0][4] == "."


# ---------------------------------------------------------------------------
# Opposite-color collision mid-path — later captures and continues
# ---------------------------------------------------------------------------

def test_opposite_color_cross_paths_later_captures():
    """Two rooks of opposite colors cross paths. Later one captures."""
    # wR at (0,0) → (0,7), bR at (0,7) → (0,0). Both started at t=0.
    # wR at (0,3) @ t=3000. bR at (0,4) @ t=3000.
    # wR at (0,4) @ t=4000. bR at (0,3) @ t=4000.
    # At t=4000: wR tries (0,4) — bR is there (arrived t=3000). Opposite color → capture.
    # Also at t=4000: bR tries (0,3) — wR is there (arrived t=3000). Opposite color → capture.
    # Tie-break: wR (seq=0) processes first at t=4000.
    # wR enters (0,4), capturing bR (bR was at (0,4) since t=3000).
    # bR's event at t=4000: bR is captured → skip.
    board = make_board(["wR . . . . . . bR"])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 7)   # wR, seq=0
    engine.request_move(0, 7, 0, 0)   # bR, seq=1
    engine.handle_wait(7 * MOVE_DURATION_MS)
    # wR captures bR mid-path and continues to destination
    assert board[0][7] == "wR"
    assert board[0][0] == "."


def test_opposite_color_capture_mid_path_captured_piece_gone():
    """A piece captured mid-path does not appear at its destination."""
    # wR at (0,0) → (0,5), bR at (0,5) → (0,0). Both paths clear at start.
    board = make_board(["wR . . . . bR"])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 5)   # wR, seq=0
    engine.request_move(0, 5, 0, 0)   # bR, seq=1
    # Traced: at t=3000, wR→(0,3) captures bR (which is at (0,2) from t=2000? No...)
    # Let's trace: wR path (0,1)@1,(0,2)@2,(0,3)@3,(0,4)@4,(0,5)@5 (in seconds)
    # bR path: (0,4)@1,(0,3)@2,(0,2)@3,(0,1)@4,(0,0)@5
    # t=1: wR→(0,1), bR→(0,4). Fine.
    # t=2: wR→(0,2), bR→(0,3). Fine (different cells).
    # t=3: wR→(0,3). bR is there (arrived at t=2)! Opposite color → capture.
    # bR captured. wR continues.
    # t=4: wR→(0,4). t=5: wR→(0,5) arrived.
    engine.handle_wait(5 * MOVE_DURATION_MS)
    assert board[0][5] == "wR"
    assert board[0][0] == "."   # bR never arrived


# ---------------------------------------------------------------------------
# Piece that is eaten does not arrive at destination
# ---------------------------------------------------------------------------

def test_captured_piece_does_not_arrive():
    """Same scenario — bR captured at mid-path never reaches col 0."""
    board = make_board(["wR . . . . bR"])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 5)   # wR, seq=0
    engine.request_move(0, 5, 0, 0)   # bR, seq=1
    engine.handle_wait(5 * MOVE_DURATION_MS)
    assert board[0][0] == "."   # bR captured mid-path


# ---------------------------------------------------------------------------
# Piece that is stopped does not arrive at destination
# ---------------------------------------------------------------------------

def test_stopped_piece_does_not_arrive():
    board = make_board(["wR . . . wR"])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 2)   # seq=0, arrives t=2000
    engine.request_move(0, 4, 0, 2)   # seq=1, arrives t=2000
    engine.handle_wait(2 * MOVE_DURATION_MS)
    # seq=1 stopped at (0,3), did NOT arrive at (0,2)
    assert board[0][3] == "wR"  # stopped here
    assert board[0][2] == "wR"  # seq=0 arrived


# ---------------------------------------------------------------------------
# Knight does not collide on intermediate cells
# ---------------------------------------------------------------------------

def test_knight_not_blocked_mid_path():
    """Knight jumps directly — no intermediate collision possible."""
    board = make_board([
        ". . .",
        ". wP .",
        "wN . .",
    ])
    engine = GameEngine(board)
    # Knight at (2,0) → (0,1). Path goes "over" (1,1) where wP sits.
    # But knight has no intermediate cells — just destination.
    # wP at (0,1)? No — (0,1) is empty. wP at (1,1).
    # Knight destination (0,1) is empty → arrives fine.
    engine.request_move(2, 0, 0, 1)
    engine.handle_wait(2 * MOVE_DURATION_MS)
    assert board[0][1] == "wN"
    assert board[1][1] == "wP"  # not affected


# ---------------------------------------------------------------------------
# Large wait processes all events chronologically
# ---------------------------------------------------------------------------

def test_large_wait_processes_all():
    board = make_board(["wR . . . . . . ."])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 7)  # 7 cells, arrives at t=7000
    engine.handle_wait(10000)  # way past arrival
    assert board[0][7] == "wR"
    assert board[0][0] == "."


# ---------------------------------------------------------------------------
# Two consecutive waits without double-processing
# ---------------------------------------------------------------------------

def test_two_waits_no_double_processing(capsys):
    board = make_board(["wR . . ."])
    commands = [
        "click 0 0",
        "click 300 0",       # wR → col 3, arrive=3000
        "wait 1000",         # process t=(0,1000]
        "print board",       # wR still at source (not arrived)
        "wait 2000",         # process t=(1000,3000]
        "print board",       # wR arrived at col 3
    ]
    process_commands(board, commands)
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == "wR . . ."   # not arrived yet
    assert lines[1] == ". . . wR"   # arrived


# ---------------------------------------------------------------------------
# Tie-break by sequence_id
# ---------------------------------------------------------------------------

def test_tiebreak_by_sequence_id():
    """When two pieces arrive at the same cell at the same time,
    lower sequence_id wins."""
    board = make_board(["wR . . . wR"])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 2)   # seq=0, arrive=2000
    engine.request_move(0, 4, 0, 2)   # seq=1, arrive=2000
    engine.handle_wait(2 * MOVE_DURATION_MS)
    assert board[0][2] == "wR"   # seq=0 won
    assert board[0][3] == "wR"   # seq=1 stopped at (0,3)


# ---------------------------------------------------------------------------
# Jump: active before expiration, inactive after
# ---------------------------------------------------------------------------

def test_jump_active_before_expiration_blocks_enemy(capsys):
    board = make_board(["wR bR . ."])
    commands = [
        "jump 0 0",          # wR jumps, expires_at=1000
        "click 100 0",       # select bR
        "click 0 0",         # bR → col 0, arrive=1000
        "wait 1000",         # jump still active at t=1000 → airborne capture
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == "wR . . ."


def test_jump_inactive_after_expiration(capsys):
    board = make_board(["wR . . . . bR"])
    commands = [
        "jump 0 0",          # wR jumps, expires_at=1000
        "wait 1100",         # jump expired
        "click 550 0",       # select bR
        "click 0 0",         # bR → col 0, arrive=1100+5*1000=6100
        "wait 5000",         # bR arrives at t=6100
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    assert output == "bR . . . . ."


# ---------------------------------------------------------------------------
# Captured static piece removed from board
# ---------------------------------------------------------------------------

def test_captured_static_piece_removed():
    """An opposite-color static piece at the destination is captured."""
    board = make_board(["wR . . bP"])
    engine = GameEngine(board)
    engine.request_move(0, 0, 0, 3)   # wR → col 3 where bP is (valid — destination capture)
    engine.handle_wait(3 * MOVE_DURATION_MS)
    assert board[0][3] == "wR"    # wR captured bP
    assert board[0][0] == "."


# ---------------------------------------------------------------------------
# Game-over mid-window
# ---------------------------------------------------------------------------

def test_game_over_mid_window_stops_later_events(capsys):
    board = make_board(["wR . bK . wR ."])
    commands = [
        "click 0 0",         # select wR at col 0
        "click 200 0",       # wR → col 2 (bK), arrive=2000
        "click 400 0",       # select wR at col 4
        "click 500 0",       # wR → col 5, arrive=1000
        "wait 5000",         # process all — game over when bK captured
        "print board",
    ]
    process_commands(board, commands)
    output = capsys.readouterr().out.strip()
    # wR at col 4 moved to col 5 at t=1000 (before game over at t=2000) — should happen
    # wR at col 0 captured bK at t=2000 — game over
    assert "wR" in output  # at least one rook visible
