from __future__ import annotations

import pathlib

import cv2
import numpy as np

class Img:
    def __init__(self):
        self.img = None

    def read(self, path: str | pathlib.Path,
             size: tuple[int, int] | None = None,
             keep_aspect: bool = False,
             interpolation: int = cv2.INTER_AREA) -> "Img":
        """
        Load `path` into self.img and **optionally resize**.

        Parameters
        ----------
        path : str | Path
            Image file to load.
        size : (width, height) | None
            Target size in pixels.  If None, keep original.
        keep_aspect : bool
            • False  → resize exactly to `size`
            • True   → shrink so the *longer* side fits `size` while
                       preserving aspect ratio (no cropping).
        interpolation : OpenCV flag
            E.g.  `cv2.INTER_AREA` for shrink, `cv2.INTER_LINEAR` for enlarge.

        Returns
        -------
        Img
            `self`, so you can chain:  `sprite = Img().read("foo.png", (64,64))`
        """
        path = str(path)
        self.img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if self.img is None:
            raise FileNotFoundError(f"Cannot load image: {path}")

        if size is not None:
            target_w, target_h = size
            h, w = self.img.shape[:2]

            if keep_aspect:
                scale = min(target_w / w, target_h / h)
                new_w, new_h = int(w * scale), int(h * scale)
            else:
                new_w, new_h = target_w, target_h

            self.img = cv2.resize(self.img, (new_w, new_h), interpolation=interpolation)

        return self

    def draw_on(self, other_img, x, y):
        if self.img is None or other_img.img is None:
            raise ValueError("Both images must be loaded before drawing.")

        if self.img.shape[2] != other_img.img.shape[2]:
            if self.img.shape[2] == 3 and other_img.img.shape[2] == 4:
                self.img = cv2.cvtColor(self.img, cv2.COLOR_BGR2BGRA)
            elif self.img.shape[2] == 4 and other_img.img.shape[2] == 3:
                self.img = cv2.cvtColor(self.img, cv2.COLOR_BGRA2BGR)

        h, w = self.img.shape[:2]
        H, W = other_img.img.shape[:2]

        if y + h > H or x + w > W:
            raise ValueError("Logo does not fit at the specified position.")

        roi = other_img.img[y:y + h, x:x + w]

        if self.img.shape[2] == 4:
            b, g, r, a = cv2.split(self.img)
            mask = a / 255.0
            for c in range(3):
                roi[..., c] = (1 - mask) * roi[..., c] + mask * self.img[..., c]
        else:
            other_img.img[y:y + h, x:x + w] = self.img

    def put_text(self, txt, x, y, font_size, color=(255, 255, 255, 255), thickness=1):
        if self.img is None:
            raise ValueError("Image not loaded.")
        cv2.putText(self.img, txt, (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, font_size,
                    color, thickness, cv2.LINE_AA)

    def put_centered_text(self, txt, font_size, color=(255, 255, 255), thickness=2):
        """
        Draw text centered horizontally and vertically on the image.

        Parameters
        ----------
        txt : str
            Text to draw.
        font_size : float
            Font scale for cv2.
        color : tuple
            BGR color.
        thickness : int
            Text thickness.
        """
        if self.img is None:
            raise ValueError("Image not loaded.")

        h, w = self.img.shape[:2]
        text_size, baseline = cv2.getTextSize(
            txt, cv2.FONT_HERSHEY_SIMPLEX, font_size, thickness
        )
        text_w, text_h = text_size

        x = (w - text_w) // 2
        y = (h + text_h) // 2

        cv2.putText(self.img, txt, (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, font_size,
                    color, thickness, cv2.LINE_AA)

    def draw_rectangle(self, x, y, width, height, color=(0, 255, 255), thickness=2):
        """
        Draw a rectangle border on the image.

        Parameters
        ----------
        x, y : int
            Top-left corner in pixels.
        width, height : int
            Size of the rectangle in pixels.
        color : tuple
            BGR color tuple (default: yellow).
        thickness : int
            Border thickness in pixels.
        """
        if self.img is None:
            raise ValueError("Image not loaded.")

        pt1 = (x, y)
        pt2 = (x + width - 1, y + height - 1)
        cv2.rectangle(self.img, pt1, pt2, color, thickness)

    def fill_rectangle(self, x, y, width, height, color=(0, 255, 255)):
        """
        Draw a filled rectangle on the image.

        Parameters
        ----------
        x, y : int
            Top-left corner in pixels.
        width, height : int
            Size of the rectangle in pixels.
        color : tuple
            BGR color tuple (default: yellow).
        """
        if self.img is None:
            raise ValueError("Image not loaded.")

        if width <= 0 or height <= 0:
            return

        pt1 = (x, y)
        pt2 = (x + width - 1, y + height - 1)
        cv2.rectangle(self.img, pt1, pt2, color, thickness=-1)

    def blend_rectangle(self, x, y, width, height, color=(0, 255, 255), alpha=0.4):
        """
        Draw a semi-transparent filled rectangle on the image.

        Parameters
        ----------
        x, y : int
            Top-left corner in pixels.
        width, height : int
            Size of the rectangle in pixels.
        color : tuple
            BGR color tuple (default: yellow).
        alpha : float
            Opacity of the overlay (0.0 = invisible, 1.0 = opaque).
        """
        if self.img is None:
            raise ValueError("Image not loaded.")

        if width <= 0 or height <= 0:
            return

        h, w = self.img.shape[:2]
        # Clamp to image bounds
        x1 = max(x, 0)
        y1 = max(y, 0)
        x2 = min(x + width, w)
        y2 = min(y + height, h)

        if x2 <= x1 or y2 <= y1:
            return

        roi = self.img[y1:y2, x1:x2]
        channels = roi.shape[2] if roi.ndim == 3 else 1

        # Build fill color matching the ROI channel count.
        if channels == 4:
            fill_color = (color[0], color[1], color[2], 255)
        else:
            fill_color = color[:3] if len(color) >= 3 else color

        overlay = np.full_like(roi, fill_color)
        cv2.addWeighted(overlay, alpha, roi, 1.0 - alpha, 0, roi)

    def show(self, window_name="Image", delay_ms=1):
        if self.img is None:
            raise ValueError("Image not loaded.")

        cv2.imshow(window_name, self.img)
        return cv2.waitKey(delay_ms)
    @staticmethod
    def close_windows():
        cv2.destroyAllWindows()

    @staticmethod
    def is_window_open(window_name: str) -> bool:
        return cv2.getWindowProperty(
            window_name,
            cv2.WND_PROP_VISIBLE,
        ) >= 1

    @staticmethod
    def set_mouse_callback(window_name: str, callback) -> None:
        """
        Register an OpenCV mouse callback on the named window.

        Parameters
        ----------
        window_name : str
            The window to attach the callback to.
        callback : callable
            Function with signature (event, x, y, flags, param).
        """
        cv2.setMouseCallback(window_name, callback)