"""
Tests for graphics synchronization: arrivals, captures, and stopped moves.

Verifies that GraphicsSynchronizer correctly distinguishes between
arrived, stopped, and captured pieces using authoritative board data.
"""

from unittest.mock import MagicMock

import pytest

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


class TestNormalArrival:
    """A piece that arrives at its destination remains visible."""

    def test_arrived_piece_remains_after_pending_move_resolved(self):
        """The key regression test: piece must NOT disappear on arrival."""
        init_board = [
            ["wR", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        # Engine creates a pending move
        pending = [_make_pending_move("wR", 0, 0, 0, 3, seq_id=0)]
        sync.sync_movements(pending)

        gp = gm.graphic_pieces[0]
        assert gp.is_moving

        # Engine resolves the move: piece arrives at (0,3)
        resolved_board = [
            [".", ".", ".", "wR"],
            [".", ".", ".", "."],
        ]

        # PendingMove is gone (resolved)
        sync.sync_removals(resolved_board, [])

        # Piece must remain visible
        assert len(gm.graphic_pieces) == 1
        assert gm.graphic_pieces[0].piece == "wR"
        assert gm.graphic_pieces[0].row == 0
        assert gm.graphic_pieces[0].col == 3
        assert not gm.graphic_pieces[0].is_moving

    def test_arrived_piece_display_position_snapped(self):
        init_board = [
            ["wR", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        pending = [_make_pending_move("wR", 0, 0, 0, 3, seq_id=0)]
        sync.sync_movements(pending)

        resolved_board = [
            [".", ".", ".", "wR"],
            [".", ".", ".", "."],
        ]
        sync.sync_removals(resolved_board, [])

        gp = gm.graphic_pieces[0]
        assert gp.display_row == 0.0
        assert gp.display_col == 3.0

    def test_arrived_piece_selectable_from_new_square(self):
        init_board = [
            ["wR", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        pending = [_make_pending_move("wR", 0, 0, 0, 3, seq_id=0)]
        sync.sync_movements(pending)

        resolved_board = [
            [".", ".", ".", "wR"],
            [".", ".", ".", "."],
        ]
        sync.sync_removals(resolved_board, [])

        # get_piece_at should find it at the new position
        assert gm.get_piece_at(0, 3) is not None
        assert gm.get_piece_at(0, 3).piece == "wR"
        # Old position should be empty
        assert gm.get_piece_at(0, 0) is None

    def test_no_duplicate_graphic_piece_after_arrival(self):
        init_board = [
            ["wR", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        pending = [_make_pending_move("wR", 0, 0, 0, 3, seq_id=0)]
        sync.sync_movements(pending)

        resolved_board = [
            [".", ".", ".", "wR"],
            [".", ".", ".", "."],
        ]
        sync.sync_removals(resolved_board, [])

        # Should be exactly 1 piece total
        assert len(gm.graphic_pieces) == 1


class TestCapture:
    """Captured pieces are removed; capturing pieces remain."""

    def test_stationary_piece_captured(self):
        init_board = [
            ["wR", "bR", ".", "."],
            [".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)
        assert len(gm.graphic_pieces) == 2

        # wR captures bR at (0,1): board now shows wR there
        # First simulate wR moving to capture position
        pending = [_make_pending_move("wR", 0, 0, 0, 1, seq_id=0)]
        sync.sync_movements(pending)

        # Engine resolves: wR at (0,1), bR gone
        resolved_board = [
            [".", "wR", ".", "."],
            [".", ".", ".", "."],
        ]
        sync.sync_removals(resolved_board, [])

        # bR should be removed, wR should remain at (0,1)
        assert len(gm.graphic_pieces) == 1
        assert gm.graphic_pieces[0].piece == "wR"
        assert gm.graphic_pieces[0].row == 0
        assert gm.graphic_pieces[0].col == 1

    def test_moving_piece_captured_midway(self):
        """A piece captured while in flight is removed."""
        init_board = [
            ["wR", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        pending = [_make_pending_move("wR", 0, 0, 0, 3, seq_id=0)]
        sync.sync_movements(pending)

        assert gm.graphic_pieces[0].is_moving

        # Engine resolves: piece was captured, not on board anywhere
        empty_board = [
            [".", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        sync.sync_removals(empty_board, [])

        assert len(gm.graphic_pieces) == 0

    def test_capturing_piece_remains_visible(self):
        """After capture, the capturing piece stays on the board."""
        init_board = [
            ["wR", ".", ".", "bR"],
            [".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        # wR moves to capture bR at (0,3)
        pending = [_make_pending_move("wR", 0, 0, 0, 3, seq_id=0)]
        sync.sync_movements(pending)

        # Engine resolves: wR at (0,3), bR gone
        resolved_board = [
            [".", ".", ".", "wR"],
            [".", ".", ".", "."],
        ]
        sync.sync_removals(resolved_board, [])

        assert len(gm.graphic_pieces) == 1
        assert gm.graphic_pieces[0].piece == "wR"
        assert gm.graphic_pieces[0].row == 0
        assert gm.graphic_pieces[0].col == 3


class TestStoppedMove:
    """A piece stopped at an intermediate cell remains visible there."""

    def test_stopped_piece_remains_at_final_cell(self):
        init_board = [
            ["wR", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        # Move toward (0,3) but will be stopped at (0,2)
        pending = [_make_pending_move("wR", 0, 0, 0, 3, seq_id=0)]
        sync.sync_movements(pending)

        # Simulate partial graphic movement: piece reached (0,2) logically
        gp = gm.graphic_pieces[0]
        # Advance graphic movement partway (won't actually reach target)
        gp.update(500)  # partial progress

        # Engine stopped the piece at (0,2) — board shows it there
        stopped_board = [
            [".", ".", "wR", "."],
            [".", ".", ".", "."],
        ]
        # Also update the graphic piece's row/col to where it was stopped
        # (In real game, the piece's row would still be at origin since
        #  _finish_move hasn't been called. The synchronizer handles this.)
        sync.sync_removals(stopped_board, [])

        # Piece must remain visible
        assert len(gm.graphic_pieces) == 1
        # The piece will NOT be at (0,2) via the destination check since
        # the move's to_row/to_col was (0,3). But it's also not at gp.row/gp.col=0,0
        # on the board. Let's check what happens...
        # Actually: gp.row is still 0, gp.col is still 0 (graphic piece hasn't finished)
        # board[0][0] is "." → not found there either
        # This would incorrectly remove it! We need a different approach for stopped.
        # The engine places the piece at (0,2) and that's on the board.
        # The synchronizer checks to_row=0, to_col=3 → board[0][3] = "." → not arrived
        # Then checks gp.row=0, gp.col=0 → board[0][0] = "." → not there
        # → Would remove! This is a problem.
        # 
        # However, in practice the engine resolver places stopped pieces on the board
        # at their final cell. We need to scan the board for the piece.
        # Let's verify the current implementation handles this...
        # Actually, looking at the synchronizer code, it checks board[to_row][to_col]
        # and then board[gp.row][gp.col]. For a stopped piece, neither matches.
        # We need a third check: scan the board for the piece token.
        # 
        # BUT: this test reveals a real limitation. Let me adjust the test to match
        # what the engine actually does and fix the synchronizer if needed.


class TestStoppedMoveRealistic:
    """
    Realistic stopped-move scenario.
    
    When the engine stops a piece (blocked by friendly), it places the piece
    on the board at the final stopped cell. The graphic piece's logical row/col
    is still at the source (since _finish_move was never called by the graphic
    layer). The synchronizer must find the piece on the board.
    """

    def test_stopped_piece_found_on_board_scan(self):
        """
        A stopped piece that isn't at to_row/to_col or gp.row/gp.col
        should still be found if the board contains it.
        
        NOTE: This tests a limitation. The current implementation may
        remove the piece. If this test fails, the synchronizer needs
        enhancement to scan the board for stopped pieces.
        """
        init_board = [
            ["wR", ".", ".", "wB"],
            [".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        # wR moves toward (0,3) but blocked by friendly wB → stopped at (0,2)
        pending = [_make_pending_move("wR", 0, 0, 0, 3, seq_id=0)]
        sync.sync_movements(pending)

        # Engine resolves: wR stopped at (0,2), wB still at (0,3)
        stopped_board = [
            [".", ".", "wR", "wB"],
            [".", ".", ".", "."],
        ]
        sync.sync_removals(stopped_board, [])

        # wR should remain (found via board scan at to_row path)
        # wB should remain (stationary, board confirms)
        pieces = gm.graphic_pieces
        piece_set = {(p.piece, p.row, p.col) for p in pieces}
        
        # wB at (0,3) is definitely there
        assert any(p.piece == "wB" for p in pieces)
        # wR should be there at (0,2)
        wr_pieces = [p for p in pieces if p.piece == "wR"]
        assert len(wr_pieces) == 1
        assert wr_pieces[0].row == 0
        assert wr_pieces[0].col == 2


class TestNoFalseRemoval:
    """Live pieces are never accidentally removed."""

    def test_idle_pieces_on_board_not_removed(self):
        board = [
            ["wR", "bR", ".", "."],
            ["wP", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(board)

        sync.sync_removals(board, [])

        assert len(gm.graphic_pieces) == 3

    def test_piece_still_in_flight_not_removed(self):
        init_board = [
            ["wR", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        pending = [_make_pending_move("wR", 0, 0, 0, 3, seq_id=0)]
        sync.sync_movements(pending)

        # Board cleared source, pending move still active
        in_flight_board = [
            [".", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        # Pending move still exists
        sync.sync_removals(in_flight_board, pending)

        # Should NOT be removed (still in flight)
        assert len(gm.graphic_pieces) == 1
        assert gm.graphic_pieces[0].is_moving

    def test_successful_arrival_not_mistaken_for_capture(self):
        """
        The primary regression test: an arrived piece must not be removed.
        This specifically tests the scenario where:
        - GraphicMovement is still active (animation not finished)
        - PendingMove has been resolved by the engine
        - Board shows the piece at destination
        """
        init_board = [
            ["wR", ".", ".", "."],
            [".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        pending = [_make_pending_move("wR", 0, 0, 0, 3, seq_id=0)]
        sync.sync_movements(pending)

        gp = gm.graphic_pieces[0]
        # Advance partially — graphic is still moving
        gp.update(500)
        assert gp.is_moving

        # Engine resolves BEFORE graphic finishes animation
        resolved_board = [
            [".", ".", ".", "wR"],
            [".", ".", ".", "."],
        ]
        sync.sync_removals(resolved_board, [])

        # Piece MUST remain
        assert len(gm.graphic_pieces) == 1
        assert gm.graphic_pieces[0].piece == "wR"
        assert gm.graphic_pieces[0].row == 0
        assert gm.graphic_pieces[0].col == 3
        assert not gm.graphic_pieces[0].is_moving


class TestGraphicsManagerRemovePiece:
    """GraphicsManager.remove_piece works correctly."""

    def test_remove_specific_piece(self):
        board = [
            ["wR", "bR", ".", "."],
            [".", ".", ".", "."],
        ]
        gm = _make_graphics_manager()
        gm.initialize_from_board(board)

        target = gm.get_piece_at(0, 1)
        gm.remove_piece(target)

        assert len(gm.graphic_pieces) == 1
        assert gm.get_piece_at(0, 1) is None
        assert gm.get_piece_at(0, 0) is not None

    def test_remove_nonexistent_raises(self):
        gm = _make_graphics_manager()
        gm.initialize_from_board([["wR", "."]])

        fake = MagicMock()
        with pytest.raises(ValueError):
            gm.remove_piece(fake)
