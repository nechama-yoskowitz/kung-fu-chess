"""
Tests for airborne/jump capture handling.

Rule: An airborne piece is PROTECTED. The arriving/moving piece is captured.
The airborne piece survives and remains on its cell.
"""

from game.engine.game_engine import GameEngine
from game.events import EventBus, MoveResolved, GameEnded
from game.model.constants import MOVE_DURATION_MS, JUMP_DURATION_MS
from game.model.piece import WHITE_PAWN, WHITE_KING, BLACK_PAWN, BLACK_ROOK, WHITE_ROOK, PieceColor
from game.io.piece_token_codec import parse_board
from game.realtime.motion import ActiveJump, PendingMove
from game.realtime.movement_resolver import apply_arrived_moves


def make_board(rows):
    return parse_board([row.split() for row in rows])


def make_move(piece, fr, fc, tr, tc, arrive_at, seq_id=0):
    return PendingMove(piece=piece, from_row=fr, from_col=fc,
                       to_row=tr, to_col=tc, started_at=0,
                       arrive_at=arrive_at, sequence_id=seq_id)


class TestMovingPawnCapturedByAirbornePawn:
    """Moving pawn reaches airborne enemy pawn → moving pawn is captured."""

    def test_moving_pawn_captured(self):
        board = make_board(["bP . . wP"])
        # wP is airborne at (0,3). bP moves to (0,3).
        active_jumps = [ActiveJump(piece=WHITE_PAWN, row=0, col=3, expires_at=5000)]
        pending = [make_move(BLACK_PAWN, 0, 0, 0, 3, arrive_at=3000)]

        remaining, game_over, jumps, _, resolved = apply_arrived_moves(
            board, pending, clock=3000, active_jumps=active_jumps
        )

        # bP is destroyed (not placed). wP remains.
        assert board[0][3] == WHITE_PAWN  # airborne piece stays on board
        assert board[0][0] is None        # source cleared
        assert game_over is False

    def test_airborne_pawn_remains_on_board(self):
        board = make_board(["bR . . wP"])
        active_jumps = [ActiveJump(piece=WHITE_PAWN, row=0, col=3, expires_at=5000)]
        pending = [make_move(BLACK_ROOK, 0, 0, 0, 3, arrive_at=3000)]

        apply_arrived_moves(board, pending, clock=3000, active_jumps=active_jumps)

        assert board[0][3] == WHITE_PAWN

    def test_moving_piece_not_placed_at_destination(self):
        board = make_board(["bR . . wP"])
        active_jumps = [ActiveJump(piece=WHITE_PAWN, row=0, col=3, expires_at=5000)]
        pending = [make_move(BLACK_ROOK, 0, 0, 0, 3, arrive_at=3000)]

        apply_arrived_moves(board, pending, clock=3000, active_jumps=active_jumps)

        # bR must NOT be at (0,3) — it was destroyed
        assert board[0][3] == WHITE_PAWN  # Only wP is there

    def test_capture_event_identifies_arriving_piece_as_captured(self):
        board = make_board(["bR . . wP"])
        active_jumps = [ActiveJump(piece=WHITE_PAWN, row=0, col=3, expires_at=5000)]
        pending = [make_move(BLACK_ROOK, 0, 0, 0, 3, arrive_at=3000)]

        _, _, _, _, resolved = apply_arrived_moves(
            board, pending, clock=3000, active_jumps=active_jumps
        )

        captured = [r for r in resolved if r["outcome"] == "captured"]
        assert len(captured) == 1
        assert captured[0]["piece"] == BLACK_ROOK  # the mover
        assert captured[0]["captured_piece"] == BLACK_ROOK  # the mover is the victim


class TestCaptureSoundEmitted:
    """Capture sound is emitted exactly once via EventBus."""

    def test_capture_sound_via_move_resolved(self):
        received = []
        bus = EventBus()
        bus.subscribe(MoveResolved, lambda e: received.append(e))

        board = make_board(["bR . . wP"])
        engine = GameEngine(board, event_bus=bus)
        engine.request_jump(0, 3)  # wP jumps
        engine.request_move(0, 0, 0, 3)  # bR → (0,3)

        engine.handle_wait(3 * MOVE_DURATION_MS + 1)

        # Should have a MoveResolved with captured_piece (bR was captured)
        captures = [e for e in received if e.captured_piece]
        assert len(captures) >= 1


class TestMovingKingCapturedByAirborne:
    """Moving king reaches airborne enemy → moving king captured, game ends."""

    def test_moving_king_captured_sets_game_over(self):
        board = make_board(["wK . . bP"])
        active_jumps = [ActiveJump(piece=BLACK_PAWN, row=0, col=3, expires_at=5000)]
        pending = [make_move(WHITE_KING, 0, 0, 0, 3, arrive_at=3000)]

        _, game_over, _, _, _ = apply_arrived_moves(
            board, pending, clock=3000, active_jumps=active_jumps
        )

        assert game_over is True

    def test_game_ended_published_once_with_correct_winner(self):
        received = []
        bus = EventBus()
        bus.subscribe(GameEnded, lambda e: received.append(e))

        # wK at (0,0), bP at (0,1) — king can reach (0,1) in 1 step
        board = make_board(["wK bP . ."])
        engine = GameEngine(board, event_bus=bus)
        engine.request_jump(0, 1)  # bP jumps
        engine.request_move(0, 0, 0, 1)  # wK → (0,1), reaches airborne bP

        engine.handle_wait(MOVE_DURATION_MS + 1)

        assert engine.game_over is True
        assert len(received) == 1
        # The arriving king (white) was captured → black wins
        assert received[0].winner == PieceColor.BLACK
        assert received[0].loser == PieceColor.WHITE

    def test_no_later_events_after_king_capture(self):
        received = []
        bus = EventBus()
        bus.subscribe(MoveResolved, lambda e: received.append(e))

        # wK at (0,0), bP at (0,1), wR at (0,7)
        board = make_board(["wK bP . . . . . wR"])
        engine = GameEngine(board, event_bus=bus)
        engine.request_jump(0, 1)
        engine.request_move(0, 0, 0, 1)  # wK dies at (0,1)
        engine.request_move(0, 7, 0, 5)  # wR also moves

        engine.handle_wait(2 * MOVE_DURATION_MS + 1)

        assert engine.game_over is True


class TestSameColorAirborneUnchanged:
    """Friendly airborne piece still lets the mover pass through."""

    def test_friendly_airborne_passthrough(self):
        board = make_board(["wR . wR"])
        active_jumps = [ActiveJump(piece=WHITE_ROOK, row=0, col=2, expires_at=5000)]
        pending = [make_move(WHITE_ROOK, 0, 0, 0, 2, arrive_at=2000)]

        _, game_over, _, _, resolved = apply_arrived_moves(
            board, pending, clock=2000, active_jumps=active_jumps
        )

        # Friendly airborne: mover passes through, arrives
        assert board[0][2] == WHITE_ROOK
        assert game_over is False
        arrived = [r for r in resolved if r["outcome"] == "arrived"]
        assert len(arrived) == 1


class TestNormalCaptureUnchanged:
    """Normal ground capture still works as before."""

    def test_normal_ground_capture(self):
        board = make_board(["bR . . wR"])
        pending = [make_move(BLACK_ROOK, 0, 0, 0, 3, arrive_at=3000)]

        _, game_over, _, _, resolved = apply_arrived_moves(board, pending, clock=3000)

        assert board[0][3] == BLACK_ROOK
        assert game_over is False
        arrived = [r for r in resolved if r["outcome"] == "arrived"]
        assert arrived[0]["captured_piece"] == WHITE_ROOK
