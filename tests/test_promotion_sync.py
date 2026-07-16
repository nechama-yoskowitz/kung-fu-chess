"""
Tests for pawn promotion synchronization from engine to graphics layer.

Verifies that when a pawn reaches the promotion row and the engine
promotes it to a queen, the corresponding GraphicPiece updates correctly.
"""

from unittest.mock import MagicMock

from game.graphics.graphics_manager import GraphicsManager
from game.graphics.graphics_synchronizer import GraphicsSynchronizer
from game.realtime.motion import PendingMove


def _make_mock_sprite_manager():
    """Create a mock SpriteManager that returns mock animation data."""
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
        piece=piece,
        from_row=from_row,
        from_col=from_col,
        to_row=to_row,
        to_col=to_col,
        started_at=0,
        arrive_at=1000,
        sequence_id=seq_id,
    )


class TestWhitePawnPromotion:
    """White pawn promotes to white queen."""

    def test_white_pawn_promotes_to_queen(self):
        # White pawn at row 1 moving to row 0 (promotion row)
        init_board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wP", ".", ".", ".", ".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        # Start the move
        pending = [_make_pending_move("wP", 1, 0, 0, 0, seq_id=0)]
        sync.sync_movements(pending)

        # Engine resolves: pawn promoted to queen at (0,0)
        resolved_board = [
            ["wQ", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
        ]
        sync.sync_removals(resolved_board, [])

        # GraphicPiece should now be a queen
        assert len(gm.graphic_pieces) == 1
        gp = gm.graphic_pieces[0]
        assert gp.piece == "wQ"

    def test_promoted_piece_position_preserved(self):
        init_board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wP", ".", ".", ".", ".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        pending = [_make_pending_move("wP", 1, 0, 0, 0, seq_id=0)]
        sync.sync_movements(pending)

        resolved_board = [
            ["wQ", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
        ]
        sync.sync_removals(resolved_board, [])

        gp = gm.graphic_pieces[0]
        assert gp.row == 0
        assert gp.col == 0

    def test_promoted_piece_display_position_preserved(self):
        init_board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wP", ".", ".", ".", ".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        pending = [_make_pending_move("wP", 1, 0, 0, 0, seq_id=0)]
        sync.sync_movements(pending)

        resolved_board = [
            ["wQ", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
        ]
        sync.sync_removals(resolved_board, [])

        gp = gm.graphic_pieces[0]
        assert gp.display_row == 0.0
        assert gp.display_col == 0.0


class TestBlackPawnPromotion:
    """Black pawn promotes to black queen."""

    def test_black_pawn_promotes_to_queen(self):
        # Black pawn at row 6 moving to row 7 (promotion row for 8-row board)
        init_board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["bP", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        pending = [_make_pending_move("bP", 6, 0, 7, 0, seq_id=0)]
        sync.sync_movements(pending)

        resolved_board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["bQ", ".", ".", ".", ".", ".", ".", "."],
        ]
        sync.sync_removals(resolved_board, [])

        assert len(gm.graphic_pieces) == 1
        gp = gm.graphic_pieces[0]
        assert gp.piece == "bQ"
        assert gp.row == 7
        assert gp.col == 0


class TestPromotionNoDuplicate:
    """No duplicate GraphicPiece is created after promotion."""

    def test_no_duplicate_after_promotion(self):
        init_board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wP", ".", ".", ".", ".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        pending = [_make_pending_move("wP", 1, 0, 0, 0, seq_id=0)]
        sync.sync_movements(pending)

        resolved_board = [
            ["wQ", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
        ]
        sync.sync_removals(resolved_board, [])

        assert len(gm.graphic_pieces) == 1

    def test_get_piece_at_finds_promoted_piece(self):
        init_board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wP", ".", ".", ".", ".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        pending = [_make_pending_move("wP", 1, 0, 0, 0, seq_id=0)]
        sync.sync_movements(pending)

        resolved_board = [
            ["wQ", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
        ]
        sync.sync_removals(resolved_board, [])

        found = gm.get_piece_at(0, 0)
        assert found is not None
        assert found.piece == "wQ"


class TestPromotionAnimationReloaded:
    """Queen sprite/animation data is used after promotion."""

    def test_sprite_manager_called_with_queen_token(self):
        sprite_manager = _make_mock_sprite_manager()
        gm = GraphicsManager(sprite_manager=sprite_manager, piece_size=(50, 50))
        sync = GraphicsSynchronizer(gm)

        init_board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wP", ".", ".", ".", ".", ".", ".", "."],
        ]
        sync.initialize(init_board)

        pending = [_make_pending_move("wP", 1, 0, 0, 0, seq_id=0)]
        sync.sync_movements(pending)

        # Clear call history to isolate promote_to calls
        sprite_manager.get_animation_data.reset_mock()

        resolved_board = [
            ["wQ", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
        ]
        sync.sync_removals(resolved_board, [])

        # After promotion, animation data should be requested with "wQ"
        calls = sprite_manager.get_animation_data.call_args_list
        queen_calls = [
            c for c in calls
            if c.kwargs.get("piece") == "wQ" or (c.args and c.args[0] == "wQ")
        ]
        # At least one call for the queen piece
        assert len(queen_calls) >= 1


class TestNonPromotedPiecesUnchanged:
    """Other pieces on the board are not affected by a promotion."""

    def test_other_pieces_unchanged_after_promotion(self):
        init_board = [
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wP", "wR", ".", ".", ".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        # Only the pawn moves
        pending = [_make_pending_move("wP", 1, 0, 0, 0, seq_id=0)]
        sync.sync_movements(pending)

        resolved_board = [
            ["wQ", ".", ".", ".", ".", ".", ".", "."],
            [".", "wR", ".", ".", ".", ".", ".", "."],
        ]
        sync.sync_removals(resolved_board, [])

        assert len(gm.graphic_pieces) == 2

        rook = gm.get_piece_at(1, 1)
        assert rook is not None
        assert rook.piece == "wR"

        queen = gm.get_piece_at(0, 0)
        assert queen is not None
        assert queen.piece == "wQ"
