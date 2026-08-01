"""Screen/rectangle detection: finds the largest bright rectangular region
in a camera frame and returns its 4 corners in camera-pixel space, in the
same canonical order calibration.py uses (top_left, top_right,
bottom_right, bottom_left) so the two can be paired up positionally
without extra cross-sensor bookkeeping.

Dependency-light on purpose (OpenCV contour detection, no trained model).
Ported from the standalone DeepLens-VT prototype (2026-08-01) once camera
+ screen detection moved onto the same machine as the rest of IntuiMotion.

NEEDS REAL-WORLD VALIDATION: works against clean synthetic test images
(see tests/test_screen_detector.py) but a real screen in a real room has
glare, other bright rectangular objects (windows, posters, other
monitors), and non-uniform lighting that this simple approach hasn't been
tested against. Confirm/tune this once a real camera is attached.
"""
from dataclasses import dataclass

import cv2
import numpy as np

from .screen_modes import ScreenMode, require_implemented

CORNER_ORDER = ("top_left", "top_right", "bottom_right", "bottom_left")


class ScreenNotFoundError(RuntimeError):
    """Raised when no 4-sided rectangular contour is found in the frame."""


@dataclass
class DetectedScreen:
    corners: dict  # corner name -> (x, y) pixel coordinates
    area_px: float

    def corner_array(self):
        return np.array([self.corners[c] for c in CORNER_ORDER], dtype=float)


def _order_corners(pts):
    """Given 4 (x, y) points in any order, label them top_left/top_right/
    bottom_right/bottom_left, in standard image coordinates (origin
    top-left, y increases downward).

    Technique: top-left has the smallest x+y sum, bottom-right the
    largest. Among the remaining two, top-right has large x and small y
    (a large, positive x-y difference), bottom-left has small x and large
    y (a large, negative x-y difference) -- so top-right is argmax(diff),
    bottom-left is argmin(diff). Confirmed via a direct test against a
    known axis-aligned rectangle after an earlier version of this had
    these two swapped (argmin/argmax reversed) -- caught by the test, not
    assumed correct from the formula alone.
    """
    pts = np.array(pts, dtype=float)
    s = pts.sum(axis=1)
    diff = pts[:, 0] - pts[:, 1]
    return {
        "top_left": tuple(pts[np.argmin(s)]),
        "bottom_right": tuple(pts[np.argmax(s)]),
        "top_right": tuple(pts[np.argmax(diff)]),
        "bottom_left": tuple(pts[np.argmin(diff)]),
    }


class ScreenDetector:
    def __init__(self, mode=ScreenMode.MONITOR, min_area_fraction=0.02, approx_epsilon_fraction=0.02):
        require_implemented(mode)
        self.mode = mode
        self.min_area_fraction = min_area_fraction
        self.approx_epsilon_fraction = approx_epsilon_fraction

    def detect(self, frame):
        """frame: an HxWx3 (or HxW grayscale) uint8 array, as returned by
        Camera.read_frame(). Returns a DetectedScreen for the largest
        4-sided contour above min_area_fraction of the frame's area.
        Raises ScreenNotFoundError if none qualifies.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        frame_area = gray.shape[0] * gray.shape[1]

        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)
        edges = cv2.dilate(edges, None, iterations=1)

        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        best = None
        best_area = 0.0
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_area_fraction * frame_area:
                continue
            perimeter = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, self.approx_epsilon_fraction * perimeter, True)
            if len(approx) != 4:
                continue
            if area > best_area:
                best_area = area
                best = approx

        if best is None:
            raise ScreenNotFoundError(
                "no 4-sided contour found covering at least "
                f"{self.min_area_fraction:.1%} of the frame"
            )

        pts = best.reshape(4, 2)
        corners = _order_corners(pts)
        return DetectedScreen(corners=corners, area_px=best_area)
