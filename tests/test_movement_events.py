"""Unit tests for MovementEvent decomposition."""
import pytest
from game.realtime.motion import (
    PendingMove,
    MovementEvent,
    decompose_moves_to_events,
)
from game.model.constants import MOVE_DURATION_MS
from game.model.piece import (
    WHITE_ROOK, WHITE_BISHOP, WHITE_QUEEN, WHITE_KING, WHITE_PAWN, WHITE_KNIGHT,
    BLACK_ROOK, BLACK_PAWN,
)


def make_move(piece, from_row, from_col, to_row, to_col, started_at=0, sequence_id=0):
    distance = max(abs(to_row - from_row), abs(to_col - from_col))
    arrive_at = started_at + distance * MOVE_DURATION_MS
    return PendingMove(piece, from_row, from_col, to_row, to_col, started_at, arrive_at, sequence_id)


# ---------------------------------------------------------------------------
# 1. Rook — multiple cells
# ---------------------------------------------------------------------------

def test_rook_4_cells_produces_4_events():
    move = make_move(WHITE_ROOK, 0, 0, 0, 4, started_at=0)
    events = decompose_moves_to_events([move])
    assert len(events) == 4
    assert events[0] == MovementEvent(0, WHITE_ROOK, 0, 1, 1000, 0, False)
    assert events[1] == MovementEvent(0, WHITE_ROOK, 0, 2, 2000, 1, False)
    assert events[2] == MovementEvent(0, WHITE_ROOK, 0, 3, 3000, 2, False)
    assert events[3] == MovementEvent(0, WHITE_ROOK, 0, 4, 4000, 3, True)


# ---------------------------------------------------------------------------
# 2. Bishop
# ---------------------------------------------------------------------------

def test_bishop_3_cells_diagonal():
    move = make_move(WHITE_BISHOP, 0, 0, 3, 3, started_at=0)
    events = decompose_moves_to_events([move])
    assert len(events) == 3
    assert events[0].row == 1 and events[0].col == 1 and events[0].event_time == 1000
    assert events[1].row == 2 and events[1].col == 2 and events[1].event_time == 2000
    assert events[2].row == 3 and events[2].col == 3 and events[2].event_time == 3000
    assert events[2].is_final is True


# ---------------------------------------------------------------------------
# 3. Queen
# ---------------------------------------------------------------------------

def test_queen_horizontal_5_cells():
    move = make_move(WHITE_QUEEN, 3, 0, 3, 5, started_at=0)
    events = decompose_moves_to_events([move])
    assert len(events) == 5
    assert events[4].row == 3 and events[4].col == 5 and events[4].event_time == 5000
    assert events[4].is_final is True


# ---------------------------------------------------------------------------
# 4. King — one step
# ---------------------------------------------------------------------------

def test_king_one_step():
    move = make_move(WHITE_KING, 4, 4, 3, 5, started_at=0)
    events = decompose_moves_to_events([move])
    assert len(events) == 1
    assert events[0] == MovementEvent(0, WHITE_KING, 3, 5, 1000, 0, True)


# ---------------------------------------------------------------------------
# 5. Pawn one step
# ---------------------------------------------------------------------------

def test_pawn_one_step():
    move = make_move(WHITE_PAWN, 6, 0, 5, 0, started_at=0)
    events = decompose_moves_to_events([move])
    assert len(events) == 1
    assert events[0] == MovementEvent(0, WHITE_PAWN, 5, 0, 1000, 0, True)


# ---------------------------------------------------------------------------
# 6. Pawn double step
# ---------------------------------------------------------------------------

def test_pawn_two_step():
    move = make_move(WHITE_PAWN, 6, 0, 4, 0, started_at=0)
    events = decompose_moves_to_events([move])
    assert len(events) == 2
    assert events[0] == MovementEvent(0, WHITE_PAWN, 5, 0, 1000, 0, False)
    assert events[1] == MovementEvent(0, WHITE_PAWN, 4, 0, 2000, 1, True)


# ---------------------------------------------------------------------------
# 7. Knight — single event at arrive_at
# ---------------------------------------------------------------------------

def test_knight_single_event_at_arrive_at():
    # Knight: Chebyshev distance = 2, but only 1 path cell
    move = make_move(WHITE_KNIGHT, 4, 4, 2, 5, started_at=0)
    events = decompose_moves_to_events([move])
    assert len(events) == 1
    assert events[0].event_time == 2000  # 2 * MOVE_DURATION_MS
    assert events[0].row == 2
    assert events[0].col == 5
    assert events[0].is_final is True
    assert events[0].path_index == 0


# ---------------------------------------------------------------------------
# 8. Two moves with events at different times
# ---------------------------------------------------------------------------

def test_two_moves_different_times_sorted_chronologically():
    # Rook starts at t=0, arrives col 2 at t=2000
    # King starts at t=500, arrives at t=1500
    rook = PendingMove(WHITE_ROOK, 0, 0, 0, 2, started_at=0, arrive_at=2000, sequence_id=0)
    king = PendingMove(WHITE_KING, 1, 1, 1, 2, started_at=500, arrive_at=1500, sequence_id=1)
    events = decompose_moves_to_events([rook, king])

    times = [e.event_time for e in events]
    assert times == sorted(times)

    # Rook: t=1000 (0,1), t=2000 (0,2)
    # King: t=1500 (1,2)
    # Sorted: 1000, 1500, 2000
    assert events[0].event_time == 1000
    assert events[0].piece == WHITE_ROOK
    assert events[1].event_time == 1500
    assert events[1].piece == WHITE_KING
    assert events[2].event_time == 2000
    assert events[2].piece == WHITE_ROOK


# ---------------------------------------------------------------------------
# 9. Two moves with same event_time — creation order is tie-breaker
# ---------------------------------------------------------------------------

def test_same_time_tiebreak_by_creation_order():
    # Both arrive at same cell time, but move_index 0 comes first
    move_a = PendingMove(WHITE_ROOK, 0, 0, 0, 1, started_at=0, arrive_at=1000, sequence_id=0)
    move_b = PendingMove(WHITE_BISHOP, 1, 1, 0, 0, started_at=0, arrive_at=1000, sequence_id=1)
    events = decompose_moves_to_events([move_a, move_b])

    # Both have event_time=1000, but move_a has sequence_id=0, move_b has sequence_id=1
    same_time = [e for e in events if e.event_time == 1000]
    assert len(same_time) == 2
    assert same_time[0].sequence_id == 0  # move_a first
    assert same_time[1].sequence_id == 1  # move_b second


# ---------------------------------------------------------------------------
# 10. Last event is exactly at arrive_at
# ---------------------------------------------------------------------------

def test_last_event_matches_arrive_at():
    move = make_move(WHITE_ROOK, 0, 0, 0, 3, started_at=500)
    events = decompose_moves_to_events([move])
    last = events[-1]
    assert last.is_final is True
    assert last.event_time == move.arrive_at  # 500 + 3*1000 = 3500


def test_knight_last_event_matches_arrive_at():
    move = make_move(WHITE_KNIGHT, 0, 0, 2, 1, started_at=200)
    events = decompose_moves_to_events([move])
    assert events[-1].event_time == move.arrive_at  # 200 + 2*1000 = 2200
    assert events[-1].is_final is True


def test_started_at_offset_applied_correctly():
    # Rook from (0,0) to (0,3) starting at t=5000
    move = PendingMove(WHITE_ROOK, 0, 0, 0, 3, started_at=5000, arrive_at=8000, sequence_id=0)
    events = decompose_moves_to_events([move])
    assert events[0].event_time == 6000  # 5000 + 1*1000
    assert events[1].event_time == 7000  # 5000 + 2*1000
    assert events[2].event_time == 8000  # 5000 + 3*1000 = arrive_at
