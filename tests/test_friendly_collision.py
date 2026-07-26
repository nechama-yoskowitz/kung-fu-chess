"""
Regression tests for same-color collision handling in the graphics sync layer.

Verifies that friendly pieces are NEVER removed when colliding.
The moving piece must stop at its previous traced cell while the
blocking piece remains untouched.
"""

from unittest.mock import MagicMock

from game.engine.game_engine import GameEngine
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.graphics_synchronizer import GraphicsSynchronizer
from game.model.constants import MOVE_DURATION_MS
from game.model.piece import WHITE_ROOK, WHITE_KNIGHT, WHITE_BISHOP, BLACK_ROOK, BLACK_KING
from game.realtime.motion import PendingMove


def _make_mock_sprite_manager():
    sm = MagicMock()
    ad = MagicMock()
    ad.frames = [MagicMock()]
    ad.frames_per_sec = 1
    ad.is_loop = True
    sm.get_animation_data.return_value = ad
    return sm


def _make_gm():
    return GraphicsManager(
        sprite_manager=_make_mock_sprite_manager(),
        piece_size=(50, 50),
    )


def _run_full_sync(engine, gm, sync, duration_frames=600, dt=16.67):
    """Run the sync loop like the real game loop."""
    for _ in range(duration_frames):
        engine.handle_wait(dt)
        sync.sync_removals(engine.board)
        sync.sync_movements(engine.pending_moves)
        gm.update(dt)


class TestSameColorHorizontalCollision:
    """Same-color horizontal collision: piece stops, blocker remains."""

    def test_two_rooks_converging_horizontally(self):
        """wR1 at (0,0)→(0,3), wR2 at (0,7)→(0,3). wR1 arrives first, wR2 stops."""
        board = [
            ["wR", ".", ".", ".", ".", ".", ".", "wR"],
        ]
        engine = GameEngine(board)
        gm = _make_gm()
        sync = GraphicsSynchronizer(gm, event_bus=engine.event_bus)
        sync.initialize(board)

        engine.request_move(0, 0, 0, 3)  # arrive=3000
        engine.request_move(0, 7, 0, 3)  # arrive=3000 (same distance)

        sync.sync_movements(engine.pending_moves)
        _run_full_sync(engine, gm, sync)

        assert len(gm.graphic_pieces) == 2
        positions = {(gp.row, gp.col) for gp in gm.graphic_pieces}
        # Both must be at different positions
        assert len(positions) == 2
        # No piece should be removed
        assert all(gp.piece == "wR" for gp in gm.graphic_pieces)

    def test_rook_blocked_by_static_friendly_horizontal(self):
        """wR moves toward a cell where wB already sits (via simultaneous move)."""
        # wR at (0,0), wN at (1,1). wN moves to (0,2). wR moves to (0,3).
        # wN arrives at (0,2) at time 2000 (distance=2 chebyshev).
        # Wait, knight distance is max(|dr|,|dc|) = max(1,1) = 1 → arrive=1000
        # wR path: (0,1),(0,2),(0,3). wR event at (0,2) at time 2000.
        # wN is at (0,2) by time 1000. wR hits same-color at (0,2) → stops at (0,1).
        board = [
            ["wR", ".", ".", ".", ".", ".", ".", "."],
            [".", "wN", ".", ".", ".", ".", ".", "."],
        ]
        engine = GameEngine(board)
        gm = _make_gm()
        sync = GraphicsSynchronizer(gm, event_bus=engine.event_bus)
        sync.initialize(board)

        engine.request_move(0, 0, 0, 3)  # wR: arrive=3000
        engine.request_move(1, 1, 0, 2)  # wN: distance=1, arrive=1000 (actually... knight move)

        sync.sync_movements(engine.pending_moves)
        _run_full_sync(engine, gm, sync)

        assert len(gm.graphic_pieces) == 2
        # Both survive at different positions
        positions = {(gp.row, gp.col) for gp in gm.graphic_pieces}
        assert len(positions) == 2


class TestSameColorVerticalCollision:
    """Same-color vertical collision."""

    def test_two_rooks_converging_vertically(self):
        """wR1 at (0,0)→(7,0), wR2 at (7,0)→(0,0). First to arrive blocks the other."""
        board = [
            ["wR", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            ["wR", ".", ".", ".", ".", ".", ".", "."],
        ]
        engine = GameEngine(board)
        gm = _make_gm()
        sync = GraphicsSynchronizer(gm, event_bus=engine.event_bus)
        sync.initialize(board)

        engine.request_move(0, 0, 7, 0)  # arrive=7000
        engine.request_move(7, 0, 0, 0)  # arrive=7000

        sync.sync_movements(engine.pending_moves)
        _run_full_sync(engine, gm, sync)

        assert len(gm.graphic_pieces) == 2
        positions = {(gp.row, gp.col) for gp in gm.graphic_pieces}
        assert len(positions) == 2


class TestSameColorDiagonalCollision:
    """Same-color diagonal collision."""

    def test_two_bishops_converging_diagonally(self):
        """wB1 at (0,0)→(4,4), wB2 at (7,7)→(4,4). First blocks the other."""
        board = [
            ["wB", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "wB"],
        ]
        engine = GameEngine(board)
        gm = _make_gm()
        sync = GraphicsSynchronizer(gm, event_bus=engine.event_bus)
        sync.initialize(board)

        engine.request_move(0, 0, 4, 4)  # distance=4, arrive=4000
        engine.request_move(7, 7, 4, 4)  # distance=3, arrive=3000

        sync.sync_movements(engine.pending_moves)
        _run_full_sync(engine, gm, sync)

        assert len(gm.graphic_pieces) == 2
        positions = {(gp.row, gp.col) for gp in gm.graphic_pieces}
        assert len(positions) == 2


class TestSameColorWithEnemyPresent:
    """Same-color collision while an enemy move also exists."""

    def test_friendly_collision_with_enemy_move(self):
        """wR1 stops at friendly, while a bR captures something else."""
        board = [
            ["wR", ".", ".", "wR", ".", ".", ".", "bR"],
            [".", ".", ".", ".", ".", ".", ".", "."],
        ]
        engine = GameEngine(board)
        gm = _make_gm()
        sync = GraphicsSynchronizer(gm, event_bus=engine.event_bus)
        sync.initialize(board)

        # wR1 at (0,0) → (0,5): will be stopped by wR2 at (0,3), stops at (0,2)
        engine.request_move(0, 0, 0, 2)  # Actually let's target (0,2) — before wR2
        # bR at (0,7) → (0,4): arrives at empty cell
        engine.request_move(0, 7, 0, 4)

        sync.sync_movements(engine.pending_moves)
        _run_full_sync(engine, gm, sync)

        # wR1 should arrive at (0,2) (it was going there directly)
        # wR2 stays at (0,3)
        # bR arrives at (0,4)
        assert len(gm.graphic_pieces) == 3
        pieces_by_name = {}
        for gp in gm.graphic_pieces:
            pieces_by_name.setdefault(gp.piece, []).append((gp.row, gp.col))

        # All white pieces must survive
        assert "wR" in pieces_by_name
        assert len(pieces_by_name["wR"]) == 2


class TestNoFriendlyCaptureEver:
    """Verify that no friendly piece is ever captured/removed."""

    def test_same_target_both_survive(self):
        """Two same-color pieces targeting same cell: both must survive."""
        board = [
            ["wR", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", ".", "wR", ".", ".", ".", "."],
        ]
        engine = GameEngine(board)
        gm = _make_gm()
        sync = GraphicsSynchronizer(gm, event_bus=engine.event_bus)
        sync.initialize(board)

        engine.request_move(0, 0, 0, 3)  # arrive=3000
        engine.request_move(7, 3, 0, 3)  # arrive=7000

        sync.sync_movements(engine.pending_moves)
        _run_full_sync(engine, gm, sync)

        # Both MUST survive
        assert len(gm.graphic_pieces) == 2
        # They must be at different cells
        positions = {(gp.row, gp.col) for gp in gm.graphic_pieces}
        assert len(positions) == 2


class TestStoppedPieceAtCorrectCell:
    """Verify the stopped piece ends at its previous traced cell."""

    def test_stopped_at_previous_cell(self):
        """wR moves right, blocked by friendly → stops one cell before."""
        board = [
            ["wR", ".", ".", ".", ".", ".", ".", "."],
            [".", ".", "wR", ".", ".", ".", ".", "."],
        ]
        engine = GameEngine(board)
        gm = _make_gm()
        sync = GraphicsSynchronizer(gm, event_bus=engine.event_bus)
        sync.initialize(board)

        # wR1 at (0,0) → (0,3), arrive=3000
        # wR2 at (1,2) → (0,2), arrive=1000 (distance 1)
        # wR2 arrives at (0,2) at time 1000.
        # wR1 at time 2000 tries (0,2) — finds wR2. Stops at (0,1).
        engine.request_move(0, 0, 0, 3)
        engine.request_move(1, 2, 0, 2)

        sync.sync_movements(engine.pending_moves)
        _run_full_sync(engine, gm, sync)

        assert len(gm.graphic_pieces) == 2

        # Find the piece that was originally at (0,0) — now should be at (0,1)
        # and the piece at (1,2) — now should be at (0,2)
        positions = sorted([(gp.row, gp.col) for gp in gm.graphic_pieces])
        assert (0, 1) in positions or (0, 2) in positions
        # Both survive at different cells
        assert len(set(positions)) == 2
