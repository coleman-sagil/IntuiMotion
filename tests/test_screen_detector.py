import numpy as np
import cv2
import pytest

from intuimotion.screen_detector import ScreenDetector, ScreenNotFoundError, CORNER_ORDER
from intuimotion.screen_modes import ScreenMode, ScreenModeNotImplementedError


def _synthetic_frame(rect_tl, rect_br, frame_size=(480, 640)):
    """A dark frame with a bright filled rectangle from rect_tl to rect_br
    (both (x, y) in pixel space). Simulates a screen against a dark room.
    """
    h, w = frame_size
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.rectangle(frame, rect_tl, rect_br, (255, 255, 255), thickness=-1)
    return frame


def test_rejects_not_implemented_modes():
    with pytest.raises(ScreenModeNotImplementedError):
        ScreenDetector(mode=ScreenMode.AR)
    with pytest.raises(ScreenModeNotImplementedError):
        ScreenDetector(mode=ScreenMode.CAR)


def test_accepts_monitor_and_tv():
    ScreenDetector(mode=ScreenMode.MONITOR)
    ScreenDetector(mode=ScreenMode.TV)


def test_detects_a_clean_synthetic_rectangle():
    frame = _synthetic_frame((100, 80), (500, 400))
    detector = ScreenDetector()
    result = detector.detect(frame)
    assert set(result.corners.keys()) == set(CORNER_ORDER)


def test_detected_corners_are_labeled_correctly():
    frame = _synthetic_frame((100, 80), (500, 400))
    detector = ScreenDetector()
    result = detector.detect(frame)

    tl = result.corners["top_left"]
    tr = result.corners["top_right"]
    br = result.corners["bottom_right"]
    bl = result.corners["bottom_left"]

    # top_left should be the smallest-x, smallest-y corner; bottom_right
    # the largest-x, largest-y; allow a few px of contour-approximation slack
    assert tl[0] < tr[0] and tl[0] < br[0]
    assert tl[1] < bl[1] and tl[1] < br[1]
    assert br[0] > bl[0] and br[0] > tl[0]
    assert br[1] > tr[1] and br[1] > tl[1]
    assert abs(tl[0] - 100) < 10 and abs(tl[1] - 80) < 10
    assert abs(br[0] - 500) < 10 and abs(br[1] - 400) < 10


def test_raises_when_no_rectangle_present():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)  # uniform, no edges at all
    detector = ScreenDetector()
    with pytest.raises(ScreenNotFoundError):
        detector.detect(frame)


def test_ignores_rectangles_smaller_than_min_area_fraction():
    # A tiny rectangle -- e.g. a picture-in-picture window, not the screen itself
    frame = _synthetic_frame((10, 10), (30, 25), frame_size=(480, 640))
    detector = ScreenDetector(min_area_fraction=0.02)
    with pytest.raises(ScreenNotFoundError):
        detector.detect(frame)


def test_picks_the_largest_rectangle_when_multiple_present():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    # small rectangle (a decoy)
    cv2.rectangle(frame, (20, 20), (80, 60), (120, 120, 120), thickness=-1)
    # large rectangle (the real screen)
    cv2.rectangle(frame, (100, 80), (550, 420), (255, 255, 255), thickness=-1)

    detector = ScreenDetector()
    result = detector.detect(frame)
    tl = result.corners["top_left"]
    assert abs(tl[0] - 100) < 10 and abs(tl[1] - 80) < 10


def test_grayscale_frame_also_works():
    frame = _synthetic_frame((100, 80), (500, 400))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    detector = ScreenDetector()
    result = detector.detect(gray)
    assert set(result.corners.keys()) == set(CORNER_ORDER)
