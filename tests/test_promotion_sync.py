"""
Tests for pawn promotion synchronization via MoveResolved events.

Verifies that when a pawn reaches the promotion row and the engine
promotes it, the MoveResolved event updates the GraphicPiece correctly.
"""

from unittest.mock import MagicMock

from game.events import EventBus, MoveResolved
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.graphics_synchronizer import GraphicsSynchronizer
from game.model.piece import WHITE_PAWN, WHITE_QUEEN, BLACK_PAWN, BLACK_QUEEN
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


class TestWhitePawnPromotion:
    """White pawn promotes to white queen via event."""

    def test_white_pawn_promotes_to_queen(self):
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)
        sync.initialize([[".", "."], ["wP", "."]])

        sync.sync_movements([_make_pending_move("wP", 1, 0, 0, 0, seq_id=0)])

        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_PAWN, outcome="arrived",
            final_row=0, final_col=0, promoted_to=WHITE_QUEEN,
        ))

        assert len(gm.graphic_pieces) == 1
        assert gm.graphic_pieces[0].piece == "wQ"

    def test_promoted_piece_position_preserved(self):
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)
        sync.initialize([[".", "."], ["wP", "."]])

        sync.sync_movements([_make_pending_move("wP", 1, 0, 0, 0, seq_id=0)])

        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_PAWN, outcome="arrived",
            final_row=0, final_col=0, promoted_to=WHITE_QUEEN,
        ))

        gp = gm.graphic_pieces[0]
        assert gp.row == 0
        assert gp.col == 0
        assert gp.display_row == 0.0
        assert gp.display_col == 0.0


class TestBlackPawnPromotion:
    """Black pawn promotes to black queen."""

    def test_black_pawn_promotes_to_queen(self):
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)
        sync.initialize([[".", "."], [".", "."], ["bP", "."]])

        sync.sync_movements([_make_pending_move("bP", 2, 0, 3, 0, seq_id=0)])

        bus.publish(MoveResolved(
            sequence_id=0, piece=BLACK_PAWN, outcome="arrived",
            final_row=3, final_col=0, promoted_to=BLACK_QUEEN,
        ))

        assert len(gm.graphic_pieces) == 1
        assert gm.graphic_pieces[0].piece == "bQ"


class TestPromotionNoDuplicate:
    """No duplicate GraphicPiece is created after promotion."""

    def test_no_duplicate_after_promotion(self):
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)
        sync.initialize([[".", "."], ["wP", "."]])

        sync.sync_movements([_make_pending_move("wP", 1, 0, 0, 0, seq_id=0)])

        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_PAWN, outcome="arrived",
            final_row=0, final_col=0, promoted_to=WHITE_QUEEN,
        ))

        assert len(gm.graphic_pieces) == 1


class TestPromotionAnimationReloaded:
    """Queen sprite data is requested after promotion."""

    def test_sprite_manager_called_with_queen_token(self):
        sprite_manager = _make_mock_sprite_manager()
        gm = GraphicsManager(sprite_manager=sprite_manager, piece_size=(50, 50))
        bus = EventBus()
        sync = GraphicsSynchronizer(gm, event_bus=bus)
        sync.initialize([[".", "."], ["wP", "."]])

        sync.sync_movements([_make_pending_move("wP", 1, 0, 0, 0, seq_id=0)])
        sprite_manager.get_animation_data.reset_mock()

        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_PAWN, outcome="arrived",
            final_row=0, final_col=0, promoted_to=WHITE_QUEEN,
        ))

        calls = sprite_manager.get_animation_data.call_args_list
        queen_calls = [
            c for c in calls
            if c.kwargs.get("piece") == "wQ" or (c.args and c.args[0] == "wQ")
        ]
        assert len(queen_calls) >= 1


class TestNonPromotedPiecesUnchanged:
    """Other pieces are not affected by a promotion event."""

    def test_other_pieces_unchanged(self):
        bus = EventBus()
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm, event_bus=bus)
        sync.initialize([[".", "."], ["wP", "wR"]])

        sync.sync_movements([_make_pending_move("wP", 1, 0, 0, 0, seq_id=0)])

        bus.publish(MoveResolved(
            sequence_id=0, piece=WHITE_PAWN, outcome="arrived",
            final_row=0, final_col=0, promoted_to=WHITE_QUEEN,
        ))

        assert len(gm.graphic_pieces) == 2
        rook = gm.get_piece_at(1, 1)
        assert rook is not None
        assert rook.piece == "wR"
