"""
Tests for Img.blend_rectangle — semi-transparent overlay drawing.

Verifies correct behavior on both 3-channel (BGR) and 4-channel (BGRA) images.
"""

import numpy as np

from game.graphics.img import Img


def _make_img_bgr(width=100, height=100, fill=(0, 0, 0)):
    """Create an Img with a solid BGR image."""
    img = Img()
    img.img = np.full((height, width, 3), fill, dtype=np.uint8)
    return img


def _make_img_bgra(width=100, height=100, fill=(0, 0, 0, 255)):
    """Create an Img with a solid BGRA image."""
    img = Img()
    img.img = np.full((height, width, 4), fill, dtype=np.uint8)
    return img


class TestBlendRectangleBGR:
    """Blending onto a 3-channel BGR image."""

    def test_no_crash_on_bgr(self):
        img = _make_img_bgr(100, 100, fill=(0, 0, 0))
        # Should not raise
        img.blend_rectangle(10, 10, 20, 20, color=(0, 255, 255), alpha=0.5)

    def test_output_shape_unchanged_bgr(self):
        img = _make_img_bgr(100, 100)
        img.blend_rectangle(10, 10, 20, 20, color=(0, 255, 255), alpha=0.5)
        assert img.img.shape == (100, 100, 3)

    def test_pixels_inside_blended_bgr(self):
        img = _make_img_bgr(100, 100, fill=(0, 0, 0))
        img.blend_rectangle(10, 10, 20, 20, color=(0, 255, 255), alpha=0.5)
        # Center pixel of rectangle should be blended
        pixel = img.img[20, 20]
        # Black + yellow at 50% = ~(0, 127, 127)
        assert pixel[1] > 100  # Green channel significantly above 0
        assert pixel[2] > 100  # Red channel significantly above 0

    def test_pixels_outside_unchanged_bgr(self):
        img = _make_img_bgr(100, 100, fill=(50, 50, 50))
        img.blend_rectangle(10, 10, 20, 20, color=(0, 255, 255), alpha=0.5)
        # Pixel outside the rectangle should remain unchanged
        assert np.array_equal(img.img[0, 0], [50, 50, 50])
        assert np.array_equal(img.img[99, 99], [50, 50, 50])


class TestBlendRectangleBGRA:
    """Blending onto a 4-channel BGRA image."""

    def test_no_crash_on_bgra(self):
        img = _make_img_bgra(100, 100, fill=(0, 0, 0, 255))
        # Should not raise
        img.blend_rectangle(10, 10, 20, 20, color=(0, 255, 255), alpha=0.5)

    def test_output_shape_unchanged_bgra(self):
        img = _make_img_bgra(100, 100)
        img.blend_rectangle(10, 10, 20, 20, color=(0, 255, 255), alpha=0.5)
        assert img.img.shape == (100, 100, 4)

    def test_pixels_inside_blended_bgra(self):
        img = _make_img_bgra(100, 100, fill=(0, 0, 0, 255))
        img.blend_rectangle(10, 10, 20, 20, color=(0, 255, 255), alpha=0.5)
        pixel = img.img[20, 20]
        # B, G, R channels blended
        assert pixel[1] > 100  # Green
        assert pixel[2] > 100  # Red
        # Alpha channel: blended between 255 (overlay) and 255 (original) → 255
        assert pixel[3] == 255

    def test_pixels_outside_unchanged_bgra(self):
        img = _make_img_bgra(100, 100, fill=(50, 50, 50, 200))
        img.blend_rectangle(10, 10, 20, 20, color=(0, 255, 255), alpha=0.5)
        assert np.array_equal(img.img[0, 0], [50, 50, 50, 200])
        assert np.array_equal(img.img[99, 99], [50, 50, 50, 200])

    def test_alpha_channel_preserved_with_partial_blend(self):
        """Original alpha=128 blended with overlay alpha=255 at 50%."""
        img = _make_img_bgra(100, 100, fill=(0, 0, 0, 128))
        img.blend_rectangle(10, 10, 20, 20, color=(0, 255, 255), alpha=0.5)
        pixel = img.img[20, 20]
        # Alpha: 0.5*255 + 0.5*128 = 127.5 + 64 ≈ 191
        assert 185 <= pixel[3] <= 197


class TestBlendRectangleEdgeCases:
    """Edge cases for blend_rectangle."""

    def test_zero_width_no_op(self):
        img = _make_img_bgr(100, 100, fill=(50, 50, 50))
        img.blend_rectangle(10, 10, 0, 20, color=(0, 255, 255))
        assert np.all(img.img == 50)

    def test_zero_height_no_op(self):
        img = _make_img_bgr(100, 100, fill=(50, 50, 50))
        img.blend_rectangle(10, 10, 20, 0, color=(0, 255, 255))
        assert np.all(img.img == 50)

    def test_full_image_blend(self):
        img = _make_img_bgra(50, 50, fill=(0, 0, 0, 255))
        img.blend_rectangle(0, 0, 50, 50, color=(255, 255, 255), alpha=1.0)
        # Full opacity white overlay → all pixels should be white
        assert np.all(img.img[:, :, :3] == 255)
