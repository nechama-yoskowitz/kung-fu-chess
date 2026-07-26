"""
Tests for EventBus and MoveResolved event publishing.

Verifies subscribe/publish mechanics and that the engine publishes
MoveResolved events with correct authoritative data.
"""

from game.events import EventBus, MoveResolved
from game.engine.game_engine import GameEngine
from game.model.constants import MOVE_DURATION_MS
from game.model.piece import WHITE_ROOK, WHITE_BISHOP, WHITE_QUEEN, BLACK_PAWN, BLACK_KING, PieceColor
from game.io.piece_token_codec import parse_board


class TestEventBusSubscribePublish:
    """Core EventBus mechanics."""

    def test_subscribe_and_receive(self):
        bus = EventBus()
        received = []
        bus.subscribe(MoveResolved, lambda e: received.append(e))

        event = MoveResolved(
            sequence_id=0, piece=WHITE_ROOK, outcome="arrived",
            final_row=0, final_col=3, promoted_to=None,
        )
        bus.publish(event)

        assert len(received) == 1
        assert received[0] is event

    def test_multiple_listeners(self):
        bus = EventBus()
        results_a = []
        results_b = []
        bus.subscribe(MoveResolved, lambda e: results_a.append(e))
        bus.subscribe(MoveResolved, lambda e: results_b.append(e))

        event = MoveResolved(
            sequence_id=1, piece=WHITE_BISHOP, outcome="captured",
            final_row=None, final_col=None, promoted_to=None,
        )
        bus.publish(event)

        assert len(results_a) == 1
        assert len(results_b) == 1

    def test_no_listeners_no_crash(self):
        bus = EventBus()
        event = MoveResolved(
            sequence_id=0, piece=WHITE_ROOK, outcome="arrived",
            final_row=0, final_col=0, promoted_to=None,
        )
        bus.publish(event)  # Should not raise

    def test_listener_receives_exact_event_data(self):
        bus = EventBus()
        received = []
        bus.subscribe(MoveResolved, lambda e: received.append(e))

        bus.publish(MoveResolved(
            sequence_id=42, piece=BLACK_PAWN, outcome="stopped",
            final_row=5, final_col=3, promoted_to=None,
        ))

        e = received[0]
        assert e.sequence_id == 42
        assert e.piece == BLACK_PAWN
        assert e.outcome == "stopped"
        assert e.final_row == 5
        assert e.final_col == 3
        assert e.promoted_to is None

    def test_unrelated_event_type_not_received(self):
        bus = EventBus()
        received = []
        bus.subscribe(MoveResolved, lambda e: received.append(e))

        # Publish something else entirely
        bus.publish("not_an_event")

        assert len(received) == 0


class TestMoveResolvedPublishedByEngine:
    """Engine publishes MoveResolved with correct data."""

    def test_arrived_event_has_correct_final_cell(self):
        received = []
        bus = EventBus()
        bus.subscribe(MoveResolved, lambda e: received.append(e))

        board = parse_board([["wR", ".", ".", "."]])
        engine = GameEngine(board, event_bus=bus)
        engine.request_move(0, 0, 0, 2)
        engine.handle_wait(2 * MOVE_DURATION_MS + 1)

        arrived = [e for e in received if e.outcome == "arrived"]
        assert len(arrived) == 1
        assert arrived[0].final_row == 0
        assert arrived[0].final_col == 2

    def test_stopped_event_has_previous_traced_cell(self):
        received = []
        bus = EventBus()
        bus.subscribe(MoveResolved, lambda e: received.append(e))

        # Two rooks converging: wR1 from (0,0)→(0,3), wR2 from (1,2)→(0,2)
        # wR2 arrives at (0,2) first. wR1 stops at (0,1).
        board = parse_board([
            ["wR", ".", ".", "."],
            [".", ".", "wR", "."],
        ])
        engine = GameEngine(board, event_bus=bus)
        engine.request_move(0, 0, 0, 3)  # arrive=3000
        engine.request_move(1, 2, 0, 2)  # arrive=1000

        engine.handle_wait(4 * MOVE_DURATION_MS)

        stopped = [e for e in received if e.outcome == "stopped"]
        assert len(stopped) == 1
        assert stopped[0].final_row == 0
        assert stopped[0].final_col == 1

    def test_captured_event_has_no_final_cell(self):
        received = []
        bus = EventBus()
        bus.subscribe(MoveResolved, lambda e: received.append(e))

        # bR captures wR
        board = parse_board([["wR", ".", ".", "bR"]])
        engine = GameEngine(board, event_bus=bus)
        engine.request_move(0, 0, 0, 2)  # wR → (0,2)
        engine.request_move(0, 3, 0, 0)  # bR → (0,0), passes through (0,2)

        engine.handle_wait(4 * MOVE_DURATION_MS)

        captured = [e for e in received if e.outcome == "captured"]
        assert len(captured) >= 1
        # The captured piece should have no final cell
        for c in captured:
            assert c.final_row is None
            assert c.final_col is None

    def test_promotion_event_contains_promoted_to(self):
        received = []
        bus = EventBus()
        bus.subscribe(MoveResolved, lambda e: received.append(e))

        # White pawn at row 1 moves to row 0 (promotion)
        board = parse_board([
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wP", ".", ".", ".", ".", ".", ".", "."],
        ])
        engine = GameEngine(board, event_bus=bus)
        engine.request_move(1, 0, 0, 0)
        engine.handle_wait(MOVE_DURATION_MS + 1)

        arrived = [e for e in received if e.outcome == "arrived"]
        assert len(arrived) == 1
        assert arrived[0].promoted_to == WHITE_QUEEN
        assert arrived[0].final_row == 0
        assert arrived[0].final_col == 0

    def test_event_published_exactly_once_per_resolved_move(self):
        received = []
        bus = EventBus()
        bus.subscribe(MoveResolved, lambda e: received.append(e))

        board = parse_board([["wR", ".", ".", "."]])
        engine = GameEngine(board, event_bus=bus)
        engine.request_move(0, 0, 0, 2)

        # Advance in multiple increments
        for _ in range(200):
            engine.handle_wait(16.67)

        # Should be exactly 1 event total
        assert len(received) == 1

    def test_event_ordering_after_board_mutation(self):
        """Event is published after the board reflects the resolution."""
        board_snapshots = []
        bus = EventBus()

        board = parse_board([["wR", ".", ".", "."]])
        engine = GameEngine(board, event_bus=bus)

        def capture_board_state(event):
            # At this point, the board should already be updated
            board_snapshots.append(list(board[0]))

        bus.subscribe(MoveResolved, capture_board_state)

        engine.request_move(0, 0, 0, 2)
        engine.handle_wait(2 * MOVE_DURATION_MS + 1)

        assert len(board_snapshots) == 1
        # Board should show wR at (0,2) when the event fires
        assert board_snapshots[0][2] == WHITE_ROOK
        assert board_snapshots[0][0] is None


class TestEventBusUnsubscribe:
    """EventBus.unsubscribe behavior."""

    def test_unsubscribed_handler_no_longer_receives_events(self):
        bus = EventBus()
        received = []
        handler = lambda e: received.append(e)

        bus.subscribe(MoveResolved, handler)
        bus.unsubscribe(MoveResolved, handler)

        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_ROOK, outcome="arrived",
            final_row=0, final_col=0, promoted_to=None,
        ))

        assert len(received) == 0

    def test_unsubscribing_one_does_not_remove_others(self):
        bus = EventBus()
        results_a = []
        results_b = []
        handler_a = lambda e: results_a.append(e)
        handler_b = lambda e: results_b.append(e)

        bus.subscribe(MoveResolved, handler_a)
        bus.subscribe(MoveResolved, handler_b)
        bus.unsubscribe(MoveResolved, handler_a)

        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_ROOK, outcome="arrived",
            final_row=0, final_col=0, promoted_to=None,
        ))

        assert len(results_a) == 0
        assert len(results_b) == 1

    def test_unsubscribe_unknown_handler_is_noop(self):
        bus = EventBus()
        other_handler = lambda e: None

        bus.subscribe(MoveResolved, lambda e: None)
        # Should not raise
        bus.unsubscribe(MoveResolved, other_handler)

    def test_unsubscribe_unknown_event_type_is_noop(self):
        bus = EventBus()

        class UnknownEvent:
            pass

        # No subscriptions exist at all for UnknownEvent — should not raise
        bus.unsubscribe(UnknownEvent, lambda e: None)

    def test_duplicate_subscriptions_one_unsubscribe_removes_one(self):
        bus = EventBus()
        received = []
        handler = lambda e: received.append(e)

        bus.subscribe(MoveResolved, handler)
        bus.subscribe(MoveResolved, handler)
        bus.unsubscribe(MoveResolved, handler)

        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_ROOK, outcome="arrived",
            final_row=0, final_col=0, promoted_to=None,
        ))

        # One registration remains, so handler is called once
        assert len(received) == 1

    def test_removing_final_handler_cleans_event_type_entry(self):
        bus = EventBus()
        handler = lambda e: None

        bus.subscribe(MoveResolved, handler)
        bus.unsubscribe(MoveResolved, handler)

        # Internal dict should not retain the empty key
        assert MoveResolved not in bus._listeners
