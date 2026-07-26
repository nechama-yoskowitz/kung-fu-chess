"""
Tests for the GameEnded event.

Verifies that GameEnded is published exactly once with correct winner/loser
when a king is captured, and that existing behavior (MoveResolved, scoring)
is preserved.
"""

from game.events import EventBus, MoveResolved, GameEnded
from game.engine.game_engine import GameEngine
from game.model.constants import MOVE_DURATION_MS
from game.model.piece import WHITE_ROOK, BLACK_ROOK, BLACK_KING, WHITE_KING, PieceColor
from game.io.piece_token_codec import parse_board


class TestBlackKingCaptured:
    """Capturing the black king publishes GameEnded(winner=WHITE, loser=BLACK)."""

    def test_white_wins_by_capturing_black_king(self):
        received = []
        bus = EventBus()
        bus.subscribe(GameEnded, lambda e: received.append(e))

        board = parse_board([["wR", ".", ".", "bK"]])
        engine = GameEngine(board, event_bus=bus)
        engine.request_move(0, 0, 0, 3)
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)

        assert len(received) == 1
        assert received[0].winner == PieceColor.WHITE
        assert received[0].loser == PieceColor.BLACK


class TestWhiteKingCaptured:
    """Capturing the white king publishes GameEnded(winner=BLACK, loser=WHITE)."""

    def test_black_wins_by_capturing_white_king(self):
        received = []
        bus = EventBus()
        bus.subscribe(GameEnded, lambda e: received.append(e))

        board = parse_board([["bR", ".", ".", "wK"]])
        engine = GameEngine(board, event_bus=bus)
        engine.request_move(0, 0, 0, 3)
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)

        assert len(received) == 1
        assert received[0].winner == PieceColor.BLACK
        assert received[0].loser == PieceColor.WHITE


class TestGameOverTrueWhenSubscriberCalled:
    """engine.game_over is True when the GameEnded subscriber fires."""

    def test_game_over_flag_set_before_event_delivery(self):
        states = []
        bus = EventBus()

        board = parse_board([["wR", ".", ".", "bK"]])
        engine = GameEngine(board, event_bus=bus)

        def capture_state(event):
            states.append(engine.game_over)

        bus.subscribe(GameEnded, capture_state)

        engine.request_move(0, 0, 0, 3)
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)

        assert len(states) == 1
        assert states[0] is True


class TestPublishedExactlyOnce:
    """GameEnded is published exactly once even with continued time updates."""

    def test_no_duplicate_after_additional_handle_wait(self):
        received = []
        bus = EventBus()
        bus.subscribe(GameEnded, lambda e: received.append(e))

        board = parse_board([["wR", ".", ".", "bK"]])
        engine = GameEngine(board, event_bus=bus)
        engine.request_move(0, 0, 0, 3)
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)

        # Additional time updates should not produce more events
        engine.handle_wait(1000)
        engine.handle_wait(1000)
        engine.handle_wait(1000)

        assert len(received) == 1

    def test_no_duplicate_with_incremental_time(self):
        received = []
        bus = EventBus()
        bus.subscribe(GameEnded, lambda e: received.append(e))

        board = parse_board([["wR", ".", ".", "bK"]])
        engine = GameEngine(board, event_bus=bus)
        engine.request_move(0, 0, 0, 3)

        # Advance in small increments like the game loop
        for _ in range(300):
            engine.handle_wait(16.67)

        assert len(received) == 1


class TestMoveResolvedBeforeGameEnded:
    """MoveResolved for the king capture is published before GameEnded."""

    def test_event_ordering(self):
        all_events = []
        bus = EventBus()
        bus.subscribe(MoveResolved, lambda e: all_events.append(("MoveResolved", e)))
        bus.subscribe(GameEnded, lambda e: all_events.append(("GameEnded", e)))

        board = parse_board([["wR", ".", ".", "bK"]])
        engine = GameEngine(board, event_bus=bus)
        engine.request_move(0, 0, 0, 3)
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)

        event_types = [t for t, _ in all_events]
        # MoveResolved must appear before GameEnded
        mr_index = event_types.index("MoveResolved")
        ge_index = event_types.index("GameEnded")
        assert mr_index < ge_index


class TestExistingBehaviorPreserved:
    """Scoring and move-history still work correctly with king capture."""

    def test_score_still_works_for_non_king_captures(self):
        bus = EventBus()
        board = parse_board([["wR", ".", ".", "bR"]])
        engine = GameEngine(board, event_bus=bus)
        engine.request_move(0, 0, 0, 3)
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)

        assert engine.white_score == 5
        assert engine.game_over is False

    def test_king_capture_gives_zero_score(self):
        bus = EventBus()
        board = parse_board([["wR", ".", ".", "bK"]])
        engine = GameEngine(board, event_bus=bus)
        engine.request_move(0, 0, 0, 3)
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)

        assert engine.white_score == 0
        assert engine.game_over is True

    def test_game_ended_via_update_game_state(self):
        """GameEnded also works when game_over comes via advance_time in handle_wait."""
        received = []
        bus = EventBus()
        bus.subscribe(GameEnded, lambda e: received.append(e))

        board = parse_board([["wR", ".", ".", "bK"]])
        engine = GameEngine(board, event_bus=bus)
        engine.request_move(0, 0, 0, 3)

        # Use handle_wait which internally calls advance_time → _resolve
        engine.handle_wait(3 * MOVE_DURATION_MS + 1)

        assert len(received) == 1
        assert received[0].winner == PieceColor.WHITE
        assert received[0].loser == PieceColor.BLACK
        assert engine.game_over is True
