"""
Tests for jump animation synchronization from engine ActiveJump to graphics.

Verifies that GraphicsSynchronizer.sync_jumps correctly:
- starts jump animations exactly once,
- applies JUMP state to the correct piece,
- preserves position,
- detects expiration and returns to IDLE,
- handles multiple jumps independently,
- doesn't interfere with captured/removed pieces.
"""

from unittest.mock import MagicMock

from game.graphics.graphics_manager import GraphicsManager
from game.graphics.graphics_synchronizer import GraphicsSynchronizer
from game.graphics.pieces.piece_state_machine import PieceStateMachine
from game.model.piece import WHITE_ROOK, WHITE_BISHOP, WHITE_KNIGHT, BLACK_ROOK
from game.realtime.motion import ActiveJump


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


class TestJumpStartsExactlyOnce:
    """Jump animation starts exactly once per ActiveJump."""

    def test_jump_starts_on_first_sync(self):
        init_board = [["wR", ".", ".", "."]]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        jumps = [ActiveJump(piece=WHITE_ROOK, row=0, col=0, expires_at=1000)]
        sync.sync_jumps(jumps)

        gp = gm.graphic_pieces[0]
        assert gp.state == PieceStateMachine.JUMP

    def test_jump_not_restarted_on_second_sync(self):
        init_board = [["wR", ".", ".", "."]]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        jumps = [ActiveJump(piece=WHITE_ROOK, row=0, col=0, expires_at=1000)]
        sync.sync_jumps(jumps)

        sprite_mgr = gm.sprite_manager
        call_count_after_first = sprite_mgr.get_animation_data.call_count

        # Second sync — should NOT create a new animation
        sync.sync_jumps(jumps)

        assert sprite_mgr.get_animation_data.call_count == call_count_after_first


class TestJumpAppliedToCorrectPiece:
    """Jump state is applied to the piece at the correct cell."""

    def test_correct_piece_jumps(self):
        init_board = [["wR", "wB", "wN", "."]]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        # Only the bishop at (0,1) jumps
        jumps = [ActiveJump(piece=WHITE_BISHOP, row=0, col=1, expires_at=1000)]
        sync.sync_jumps(jumps)

        assert gm.get_piece_at(0, 0).state == PieceStateMachine.IDLE
        assert gm.get_piece_at(0, 1).state == PieceStateMachine.JUMP
        assert gm.get_piece_at(0, 2).state == PieceStateMachine.IDLE


class TestJumpPositionUnchanged:
    """Logical and display position remain unchanged during jump."""

    def test_position_preserved(self):
        init_board = [["wR", ".", ".", "."]]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        jumps = [ActiveJump(piece=WHITE_ROOK, row=0, col=0, expires_at=1000)]
        sync.sync_jumps(jumps)

        gp = gm.graphic_pieces[0]
        assert gp.row == 0
        assert gp.col == 0
        assert gp.display_row == 0.0
        assert gp.display_col == 0.0


class TestJumpAnimationAdvances:
    """The jump animation advances via GraphicPiece.update()."""

    def test_animation_update_called(self):
        init_board = [["wR", ".", ".", "."]]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        jumps = [ActiveJump(piece=WHITE_ROOK, row=0, col=0, expires_at=1000)]
        sync.sync_jumps(jumps)

        gp = gm.graphic_pieces[0]
        # The animation mock should respond to update
        gp.animation.update = MagicMock()
        gp.animation.is_finished = MagicMock(return_value=False)

        gp.update(100)

        gp.animation.update.assert_called_once_with(100)


class TestJumpExpiration:
    """Jump expiration returns the piece to IDLE."""

    def test_piece_returns_to_idle_on_expiry(self):
        init_board = [["wR", ".", ".", "."]]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        jumps = [ActiveJump(piece=WHITE_ROOK, row=0, col=0, expires_at=1000)]
        sync.sync_jumps(jumps)

        assert gm.graphic_pieces[0].state == PieceStateMachine.JUMP

        # Jump expires — empty list
        sync.sync_jumps([])

        assert gm.graphic_pieces[0].state == PieceStateMachine.IDLE

    def test_position_unchanged_after_expiry(self):
        init_board = [["wR", ".", ".", "."]]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        jumps = [ActiveJump(piece=WHITE_ROOK, row=0, col=0, expires_at=1000)]
        sync.sync_jumps(jumps)
        sync.sync_jumps([])

        gp = gm.graphic_pieces[0]
        assert gp.row == 0
        assert gp.col == 0


class TestMultipleJumps:
    """Multiple pieces can jump independently."""

    def test_two_pieces_jump_simultaneously(self):
        init_board = [["wR", "wB", ".", "."]]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        jumps = [
            ActiveJump(piece=WHITE_ROOK, row=0, col=0, expires_at=1000),
            ActiveJump(piece=WHITE_BISHOP, row=0, col=1, expires_at=1500),
        ]
        sync.sync_jumps(jumps)

        assert gm.get_piece_at(0, 0).state == PieceStateMachine.JUMP
        assert gm.get_piece_at(0, 1).state == PieceStateMachine.JUMP

    def test_one_expires_other_remains(self):
        init_board = [["wR", "wB", ".", "."]]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        jumps = [
            ActiveJump(piece=WHITE_ROOK, row=0, col=0, expires_at=1000),
            ActiveJump(piece=WHITE_BISHOP, row=0, col=1, expires_at=1500),
        ]
        sync.sync_jumps(jumps)

        # Only wB remains jumping
        remaining = [ActiveJump(piece=WHITE_BISHOP, row=0, col=1, expires_at=1500)]
        sync.sync_jumps(remaining)

        assert gm.get_piece_at(0, 0).state == PieceStateMachine.IDLE
        assert gm.get_piece_at(0, 1).state == PieceStateMachine.JUMP


class TestCapturedJumpingPiece:
    """A jumping piece that is captured/removed doesn't cause errors."""

    def test_removed_piece_does_not_crash_on_expiry(self):
        init_board = [["wR", ".", ".", "."]]
        gm = _make_graphics_manager()
        sync = GraphicsSynchronizer(gm)
        sync.initialize(init_board)

        jumps = [ActiveJump(piece=WHITE_ROOK, row=0, col=0, expires_at=1000)]
        sync.sync_jumps(jumps)

        # Piece is removed (captured by engine)
        gm.remove_piece(gm.graphic_pieces[0])

        # Jump expires — should not crash
        sync.sync_jumps([])

        assert len(gm.graphic_pieces) == 0
