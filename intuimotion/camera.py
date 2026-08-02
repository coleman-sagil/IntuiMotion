"""Camera capture: plain OpenCV/V4L2 video capture, works against any
UVC-compliant camera. Ported from the standalone DeepLens-VT prototype
(2026-08-01) once camera + screen detection moved onto the same machine
as the rest of IntuiMotion, making that repo's separate-machine/network-
transport design unnecessary. No AWS SDK anywhere -- DeepLens-VT
deliberately bypassed AWS's end-of-lifed DeepLens service by talking to
the camera directly; that constraint carries over even though the AWS
hardware itself isn't part of this path anymore.
"""
import cv2


class CameraError(RuntimeError):
    """Raised when the camera can't be opened or a frame can't be read."""


class Camera:
    """Thin wrapper around cv2.VideoCapture so the rest of the pipeline
    doesn't import cv2 directly, and so tests can swap in a fake instead
    of needing real hardware.
    """

    def __init__(self, source=0, width=None, height=None):
        self.source = source
        self.width = width
        self.height = height
        self._cap = None

    def open(self):
        self._cap = cv2.VideoCapture(self.source)
        if self.width:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if not self._cap.isOpened():
            raise CameraError(f"could not open camera source {self.source!r}")
        return self

    def read_frame(self):
        if self._cap is None:
            raise CameraError("camera not open -- call open() first")
        ok, frame = self._cap.read()
        if not ok:
            raise CameraError(f"failed to read a frame from source {self.source!r}")
        return frame

    def close(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()
