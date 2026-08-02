from unittest.mock import MagicMock, patch

import pytest

from intuimotion.camera import Camera, CameraError


def test_open_raises_camera_error_when_device_does_not_open():
    fake_cv2_cap = MagicMock()
    fake_cv2_cap.isOpened.return_value = False
    with patch("intuimotion.camera.cv2.VideoCapture", return_value=fake_cv2_cap):
        with pytest.raises(CameraError, match="could not open"):
            Camera(source=99).open()


def test_read_frame_before_open_raises():
    with pytest.raises(CameraError, match="not open"):
        Camera().read_frame()


def test_read_frame_failure_raises_camera_error():
    fake_cv2_cap = MagicMock()
    fake_cv2_cap.isOpened.return_value = True
    fake_cv2_cap.read.return_value = (False, None)
    with patch("intuimotion.camera.cv2.VideoCapture", return_value=fake_cv2_cap):
        cam = Camera(source=0).open()
        with pytest.raises(CameraError, match="failed to read"):
            cam.read_frame()


def test_successful_open_read_close_round_trip():
    fake_cv2_cap = MagicMock()
    fake_cv2_cap.isOpened.return_value = True
    fake_frame = object()
    fake_cv2_cap.read.return_value = (True, fake_frame)
    with patch("intuimotion.camera.cv2.VideoCapture", return_value=fake_cv2_cap):
        with Camera(source=0) as cam:
            assert cam.read_frame() is fake_frame
    fake_cv2_cap.release.assert_called_once()


def test_width_height_set_when_provided():
    fake_cv2_cap = MagicMock()
    fake_cv2_cap.isOpened.return_value = True
    with patch("intuimotion.camera.cv2.VideoCapture", return_value=fake_cv2_cap):
        Camera(source=0, width=1920, height=1080).open()
    assert fake_cv2_cap.set.call_count == 2
