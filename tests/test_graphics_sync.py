"""
Tests for graphics synchronization using MoveResolved events.

Verifies that GraphicsSynchronizer correctly handles arrived, stopped,
and captured outcomes via the event bus, and that stationary captures
are detected via board polling.
"""

from unittest.mock import MagicMock

import pytest

from game.events import EventBus, MoveResolved
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.graphics_synchronizer import GraphicsSynchronizer
from game.model.piece import WHITE_ROOK, WHITE_BISHOP, BLACK_ROOK, WHITE_PAWN, WHITE_QUEEN
from game.realtime.motion import PendingMove


def _make_mock_sprite_manager():
    sprite_manager = MagicMock()
    animation_data = MagicMock()
    animation_data.frames = [MagicMock()]
    animation_data.frames_per_sec = 1
    animation_data.is_loop = True
    sprite_manager.get_animation_data.return_value = animation_data
    return sprite_manager


def _make_graphics_manager():
    return GraphicsManager(
        sprite_manager=_make_mock_sprite_manager(),
        piece_size=(50, 50),
    )


def _make_pending_move(piece, from_row, from_col, to_row, to_col, seq_id):
    return PendingMove(
        piece=piece, from_row=from_row, from_col=from_col,
        to_row=to_row, to_col=to_col,
        started_at=0, arrive_at=1000, sequence_id=seq_id,
    )


class TestNormalArrival:
    """A piece that arrives at its destination remains visible."""

    def test_arrived_piece_remains_after_event(self):
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)

        init_board = [["wR", ".", ".", "."]]
        sync.initialize(init_board)

        pending = [_make_pending_move(WHITE_ROOK, 0, 0, 0, 3, seq_id=0)]
        sync.sync_movements(pending)
        assert gm.graphic_pieces[0].is_moving

        # Simulate engine publishing arrival event
        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_ROOK, outcome="arrived",
            final_row=0, final_col=3, promoted_to=None,
        ))

        assert len(gm.graphic_pieces) == 1
        assert gm.graphic_pieces[0].piece == "wR"
        assert gm.graphic_pieces[0].row == 0
        assert gm.graphic_pieces[0].col == 3
        assert not gm.graphic_pieces[0].is_moving

    def test_arrived_piece_display_position_snapped(self):
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)

        sync.initialize([["wR", ".", ".", "."]])
        sync.sync_movements([_make_pending_move(WHITE_ROOK, 0, 0, 0, 3, seq_id=0)])

        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_ROOK, outcome="arrived",
            final_row=0, final_col=3, promoted_to=None,
        ))

        gp = gm.graphic_pieces[0]
        assert gp.display_row == 0.0
        assert gp.display_col == 3.0

    def test_no_duplicate_after_arrival(self):
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)

        sync.initialize([["wR", ".", ".", "."]])
        sync.sync_movements([_make_pending_move(WHITE_ROOK, 0, 0, 0, 3, seq_id=0)])

        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_ROOK, outcome="arrived",
            final_row=0, final_col=3, promoted_to=None,
        ))

        assert len(gm.graphic_pieces) == 1

    def test_arrival_not_mistaken_for_capture(self):
        """The primary regression test: arrival must not remove the piece."""
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)

        sync.initialize([["wR", ".", ".", "."]])
        sync.sync_movements([_make_pending_move(WHITE_ROOK, 0, 0, 0, 3, seq_id=0)])

        # Partially advance graphic movement
        gm.graphic_pieces[0].update(500)
        assert gm.graphic_pieces[0].is_moving

        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_ROOK, outcome="arrived",
            final_row=0, final_col=3, promoted_to=None,
        ))

        assert len(gm.graphic_pieces) == 1
        assert gm.graphic_pieces[0].row == 0
        assert gm.graphic_pieces[0].col == 3


class TestCapture:
    """Captured pieces are removed; capturing pieces remain."""

    def test_moving_piece_captured(self):
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)

        sync.initialize([["wR", ".", ".", "."]])
        sync.sync_movements([_make_pending_move(WHITE_ROOK, 0, 0, 0, 3, seq_id=0)])

        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_ROOK, outcome="captured",
            final_row=None, final_col=None, promoted_to=None,
        ))

        assert len(gm.graphic_pieces) == 0

    def test_stationary_piece_captured_via_board_check(self):
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)

        sync.initialize([["wR", "bR", ".", "."]])
        assert len(gm.graphic_pieces) == 2

        # Simulate board after bR is captured by an arriving piece
        resolved_board = [["wR", ".", ".", "."]]
        sync.sync_removals(resolved_board)

        # bR removed, wR remains
        assert len(gm.graphic_pieces) == 1
        assert gm.graphic_pieces[0].piece == "wR"

    def test_capturing_piece_remains(self):
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)

        sync.initialize([["wR", ".", ".", "bR"]])

        # wR moves to capture bR at (0,3)
        sync.sync_movements([_make_pending_move(WHITE_ROOK, 0, 0, 0, 3, seq_id=0)])

        # Engine resolves: wR arrived at (0,3)
        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_ROOK, outcome="arrived",
            final_row=0, final_col=3, promoted_to=None,
        ))

        # Stationary bR removed via board check
        resolved_board = [[".", ".", ".", "wR"]]
        sync.sync_removals(resolved_board)

        assert len(gm.graphic_pieces) == 1
        assert gm.graphic_pieces[0].piece == "wR"
        assert gm.graphic_pieces[0].col == 3


class TestStoppedMove:
    """A stopped piece remains visible at its authoritative final cell."""

    def test_stopped_piece_placed_at_event_cell(self):
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)

        sync.initialize([["wR", ".", ".", "."]])
        sync.sync_movements([_make_pending_move(WHITE_ROOK, 0, 0, 0, 3, seq_id=0)])

        # Engine says piece stopped at (0,2)
        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_ROOK, outcome="stopped",
            final_row=0, final_col=2, promoted_to=None,
        ))

        assert len(gm.graphic_pieces) == 1
        assert gm.graphic_pieces[0].row == 0
        assert gm.graphic_pieces[0].col == 2
        assert not gm.graphic_pieces[0].is_moving


class TestSameTokenPiecesAssociatedBySequenceId:
    """sequence_id guarantees correct piece identity, not token matching."""

    def test_two_same_token_pieces_resolved_correctly(self):
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)

        init_board = [
            ["wR", ".", ".", ".", ".", ".", ".", "wR"],
        ]
        sync.initialize(init_board)

        # Both rooks move
        moves = [
            _make_pending_move(WHITE_ROOK, 0, 0, 0, 3, seq_id=0),
            _make_pending_move(WHITE_ROOK, 0, 7, 0, 4, seq_id=1),
        ]
        sync.sync_movements(moves)

        # seq=0 arrives at (0,3), seq=1 stopped at (0,5)
        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_ROOK, outcome="arrived",
            final_row=0, final_col=3, promoted_to=None,
        ))
        bus.publish(MoveResolved(
            sequence_id=1, piece=WHITE_ROOK, outcome="stopped",
            final_row=0, final_col=5, promoted_to=None,
        ))

        assert len(gm.graphic_pieces) == 2
        positions = {(gp.row, gp.col) for gp in gm.graphic_pieces}
        assert positions == {(0, 3), (0, 5)}


class TestPromotion:
    """Promotion event updates piece token and reloads animation."""

    def test_promotion_changes_piece_token(self):
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)

        sync.initialize([[".", "."], ["wP", "."]])
        sync.sync_movements([_make_pending_move(WHITE_PAWN, 1, 0, 0, 0, seq_id=0)])

        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_PAWN, outcome="arrived",
            final_row=0, final_col=0, promoted_to=WHITE_QUEEN,
        ))

        assert len(gm.graphic_pieces) == 1
        assert gm.graphic_pieces[0].piece == "wQ"
        assert gm.graphic_pieces[0].row == 0
        assert gm.graphic_pieces[0].col == 0


class TestGraphicsManagerRemovePiece:
    """GraphicsManager.remove_piece works correctly."""

    def test_remove_specific_piece(self):
        gm = _make_graphics_manager()
        gm.initialize_from_board([["wR", "bR", ".", "."]])

        target = gm.get_piece_at(0, 1)
        gm.remove_piece(target)

        assert len(gm.graphic_pieces) == 1
        assert gm.get_piece_at(0, 1) is None

    def test_remove_nonexistent_raises(self):
        gm = _make_graphics_manager()
        gm.initialize_from_board([["wR", "."]])

        with pytest.raises(ValueError):
            gm.remove_piece(MagicMock())
