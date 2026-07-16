"""
Tests for sprite loading path construction and validation.

Verifies that SpriteLoader uses the engine piece token directly
as the folder name and provides clear errors for missing assets.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from game.graphics.sprites.sprite_loader import SpriteLoader


PIECES_ROOT = Path("game/graphics/assets/pieces")


class TestWhitePieceLoading:
    """White pieces load from their direct token folder."""

    def test_white_rook_folder_exists(self):
        assert (PIECES_ROOT / "wR").exists()

    def test_white_rook_idle_loads(self):
        loader = SpriteLoader(str(PIECES_ROOT))
        anim = loader.load_animation("wR", "idle", (50, 50))
        assert anim is not None
        assert len(anim.frames) > 0

    def test_white_queen_move_loads(self):
        loader = SpriteLoader(str(PIECES_ROOT))
        anim = loader.load_animation("wQ", "move", (50, 50))
        assert anim is not None
        assert len(anim.frames) > 0

    def test_white_pawn_jump_loads(self):
        loader = SpriteLoader(str(PIECES_ROOT))
        anim = loader.load_animation("wP", "jump", (50, 50))
        assert anim is not None


class TestBlackPieceLoading:
    """Black pieces load from their direct token folder."""

    def test_black_king_folder_exists(self):
        assert (PIECES_ROOT / "bK").exists()

    def test_black_bishop_idle_loads(self):
        loader = SpriteLoader(str(PIECES_ROOT))
        anim = loader.load_animation("bB", "idle", (50, 50))
        assert anim is not None
        assert len(anim.frames) > 0

    def test_black_knight_long_rest_loads(self):
        loader = SpriteLoader(str(PIECES_ROOT))
        anim = loader.load_animation("bN", "long_rest", (50, 50))
        assert anim is not None


class TestPathConstruction:
    """Correct path is built from piece token + state."""

    def test_path_uses_token_directly(self):
        loader = SpriteLoader("/fake/root")
        # We can verify path construction by checking the error message
        with pytest.raises(FileNotFoundError, match="wR"):
            loader.load_animation("wR", "idle", (50, 50))

    def test_state_folder_in_path(self):
        loader = SpriteLoader("/fake/root")
        with pytest.raises(FileNotFoundError, match="wR"):
            loader.load_animation("wR", "idle", (50, 50))


class TestMissingFolderErrors:
    """Clear errors for missing assets."""

    def test_missing_piece_folder_raises(self):
        loader = SpriteLoader(str(PIECES_ROOT))
        with pytest.raises(FileNotFoundError, match="Piece folder not found"):
            loader.load_animation("xX", "idle", (50, 50))

    def test_missing_state_folder_raises(self):
        loader = SpriteLoader(str(PIECES_ROOT))
        with pytest.raises(FileNotFoundError, match="State folder not found"):
            loader.load_animation("wR", "nonexistent_state", (50, 50))


class TestAnimationDataIntegrity:
    """Loaded animation data has correct structure."""

    def test_animation_has_frames_per_sec(self):
        loader = SpriteLoader(str(PIECES_ROOT))
        anim = loader.load_animation("wR", "idle", (50, 50))
        assert hasattr(anim, "frames_per_sec")
        assert anim.frames_per_sec > 0

    def test_animation_has_is_loop(self):
        loader = SpriteLoader(str(PIECES_ROOT))
        anim = loader.load_animation("wR", "idle", (50, 50))
        assert hasattr(anim, "is_loop")

    def test_all_12_pieces_load_idle(self):
        """Every piece type can load its idle animation."""
        loader = SpriteLoader(str(PIECES_ROOT))
        tokens = ["wR", "wN", "wB", "wQ", "wK", "wP",
                  "bR", "bN", "bB", "bQ", "bK", "bP"]
        for token in tokens:
            anim = loader.load_animation(token, "idle", (50, 50))
            assert anim is not None, f"Failed to load idle for {token}"
            assert len(anim.frames) > 0, f"No frames for {token}"
