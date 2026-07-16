"""
Tests for MoveHistoryObserver — event-driven move history recording.

Verifies that the observer correctly subscribes to MoveResolved events,
builds accurate entries, and prevents duplicates.
"""

from game.events import EventBus, MoveResolved
from game.history.move_history_observer import MoveHistoryObserver
from game.history.move_entry import MoveEntry


def _make_observer(clock_ms=0):
    bus = EventBus()
    clock = [clock_ms]
    observer = MoveHistoryObserver(
        event_bus=bus,
        clock_provider=lambda: clock[0],
    )
    return bus, observer, clock


class TestSubscription:
    """Observer subscribes correctly to MoveResolved."""

    def test_receives_arrived_event(self):
        bus, obs, clock = _make_observer(clock_ms=3000)
        bus.publish(MoveResolved(
            sequence_id=0, piece="wR", outcome="arrived",
            final_row=0, final_col=3, promoted_to=None, captured_piece=None,
        ))
        assert len(obs.white_moves) == 1

    def test_receives_black_event(self):
        bus, obs, clock = _make_observer(clock_ms=5000)
        bus.publish(MoveResolved(
            sequence_id=1, piece="bN", outcome="arrived",
            final_row=2, final_col=2, promoted_to=None, captured_piece=None,
        ))
        assert len(obs.black_moves) == 1
        assert len(obs.white_moves) == 0


class TestOneEventOneEntry:
    """One MoveResolved creates exactly one history entry."""

    def test_single_event_single_entry(self):
        bus, obs, clock = _make_observer()
        bus.publish(MoveResolved(
            sequence_id=0, piece="wP", outcome="arrived",
            final_row=4, final_col=4, promoted_to=None, captured_piece=None,
        ))
        assert len(obs.white_entries) == 1
        assert obs.white_entries[0].sequence_id == 0


class TestMultipleMovesOrder:
    """Multiple moves preserve chronological order."""

    def test_order_preserved(self):
        bus, obs, clock = _make_observer()
        clock[0] = 1000
        bus.publish(MoveResolved(
            sequence_id=0, piece="wP", outcome="arrived",
            final_row=5, final_col=0, promoted_to=None, captured_piece=None,
        ))
        clock[0] = 2000
        bus.publish(MoveResolved(
            sequence_id=1, piece="wR", outcome="arrived",
            final_row=0, final_col=3, promoted_to=None, captured_piece=None,
        ))
        clock[0] = 3000
        bus.publish(MoveResolved(
            sequence_id=2, piece="wN", outcome="arrived",
            final_row=2, final_col=2, promoted_to=None, captured_piece=None,
        ))
        assert len(obs.white_entries) == 3
        assert obs.white_entries[0].timestamp_ms == 1000
        assert obs.white_entries[1].timestamp_ms == 2000
        assert obs.white_entries[2].timestamp_ms == 3000


class TestTimestamps:
    """Timestamps use the engine clock at event time."""

    def test_timestamp_from_clock_provider(self):
        bus, obs, clock = _make_observer()
        clock[0] = 4105
        bus.publish(MoveResolved(
            sequence_id=0, piece="wP", outcome="arrived",
            final_row=4, final_col=4, promoted_to=None, captured_piece=None,
        ))
        entry = obs.white_entries[0]
        assert entry.timestamp_ms == 4105
        assert "04" in entry.time_display


class TestPromotionRecording:
    """Promotions are recorded with promoted_to info."""

    def test_promotion_in_description(self):
        bus, obs, clock = _make_observer()
        bus.publish(MoveResolved(
            sequence_id=0, piece="wP", outcome="arrived",
            final_row=0, final_col=0, promoted_to="wQ", captured_piece=None,
        ))
        entry = obs.white_entries[0]
        assert entry.promoted_to == "wQ"
        assert "Queen" in entry.description

    def test_promotion_entry_fields(self):
        bus, obs, clock = _make_observer()
        bus.publish(MoveResolved(
            sequence_id=5, piece="bP", outcome="arrived",
            final_row=7, final_col=3, promoted_to="bQ", captured_piece=None,
        ))
        entry = obs.black_entries[0]
        assert entry.promoted_to == "bQ"
        assert entry.final_row == 7
        assert entry.final_col == 3


class TestStoppedMoveRecording:
    """Stopped moves are recorded with correct description."""

    def test_stopped_description(self):
        bus, obs, clock = _make_observer()
        bus.publish(MoveResolved(
            sequence_id=0, piece="wR", outcome="stopped",
            final_row=3, final_col=5, promoted_to=None, captured_piece=None,
        ))
        entry = obs.white_entries[0]
        assert entry.outcome == "stopped"
        assert "stopped" in entry.description
        assert "(3,5)" in entry.description


class TestCapturedMoveRecording:
    """Captured moves are recorded."""

    def test_captured_description(self):
        bus, obs, clock = _make_observer()
        bus.publish(MoveResolved(
            sequence_id=0, piece="wR", outcome="captured",
            final_row=None, final_col=None, promoted_to=None, captured_piece=None,
        ))
        entry = obs.white_entries[0]
        assert entry.outcome == "captured"
        assert "captured" in entry.description

    def test_capture_info_recorded(self):
        bus, obs, clock = _make_observer()
        bus.publish(MoveResolved(
            sequence_id=0, piece="wR", outcome="arrived",
            final_row=0, final_col=3, promoted_to=None, captured_piece="bQ",
        ))
        entry = obs.white_entries[0]
        assert entry.captured_piece == "bQ"
        assert "Queen" in entry.description


class TestBothObserversReceiveEvent:
    """Graphics and history both receive the same event."""

    def test_two_subscribers_same_event(self):
        bus = EventBus()
        graphics_received = []
        history_received = []

        bus.subscribe(MoveResolved, lambda e: graphics_received.append(e))

        obs = MoveHistoryObserver(
            event_bus=bus,
            clock_provider=lambda: 1000,
        )

        event = MoveResolved(
            sequence_id=7, piece="wR", outcome="arrived",
            final_row=0, final_col=5, promoted_to=None, captured_piece=None,
        )
        bus.publish(event)

        assert len(graphics_received) == 1
        assert len(obs.white_entries) == 1
        assert graphics_received[0] is event
        assert obs.white_entries[0].sequence_id == 7


class TestNoDuplicateEntries:
    """Same sequence_id published twice doesn't create duplicates."""

    def test_duplicate_event_ignored(self):
        bus, obs, clock = _make_observer()
        event = MoveResolved(
            sequence_id=0, piece="wR", outcome="arrived",
            final_row=0, final_col=3, promoted_to=None, captured_piece=None,
        )
        bus.publish(event)
        bus.publish(event)

        assert len(obs.white_entries) == 1


class TestUIReadInterface:
    """The UI-facing properties return correct display data."""

    def test_white_moves_dict_format(self):
        bus, obs, clock = _make_observer(clock_ms=2500)
        bus.publish(MoveResolved(
            sequence_id=0, piece="wR", outcome="arrived",
            final_row=0, final_col=3, promoted_to=None, captured_piece=None,
        ))
        moves = obs.white_moves
        assert len(moves) == 1
        assert "time" in moves[0]
        assert "move" in moves[0]
        assert "Rook" in moves[0]["move"]
