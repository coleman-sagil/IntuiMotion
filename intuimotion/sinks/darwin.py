"""macOS pointer backend -- Quartz `CGEvent`, via ctypes only.

No PyObjC, no third-party package: this loads ApplicationServices directly.

The permission caveat is the whole story on macOS
-------------------------------------------------
Synthetic input requires the app to be granted **Accessibility** permission
(System Settings -> Privacy & Security -> Accessibility). Without it,
`CGEventPost` silently does nothing -- no error, no exception, no event. That
silence is why `check_permission()` exists and why the factory calls it: an
honest "not permitted" beats a cursor that mysteriously never moves.

Note the grant attaches to the *host binary* (the Python interpreter, or the
packaged .app), not to the script, so a packaged build needs its own grant.
"""

from __future__ import annotations

import ctypes
import ctypes.util

from .base import PointerSink

# CGEventType (CGEventTypes.h)
_MOUSE_MOVED = 5
_LEFT_DOWN, _LEFT_UP, _LEFT_DRAGGED = 1, 2, 6
_RIGHT_DOWN, _RIGHT_UP = 3, 4
# CGMouseButton
_BUTTON_LEFT, _BUTTON_RIGHT = 0, 1
# CGEventTapLocation
_HID_EVENT_TAP = 0

_BUTTONS = {
    "left": (_LEFT_DOWN, _LEFT_UP, _BUTTON_LEFT),
    "right": (_RIGHT_DOWN, _RIGHT_UP, _BUTTON_RIGHT),
}


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


def _load():
    path = ctypes.util.find_library("ApplicationServices")
    if path is None:
        raise OSError("ApplicationServices framework not found")
    lib = ctypes.cdll.LoadLibrary(path)
    lib.CGEventCreateMouseEvent.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, _CGPoint, ctypes.c_uint32
    ]
    lib.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    lib.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    lib.CGEventGetLocation.argtypes = [ctypes.c_void_p]
    lib.CGEventGetLocation.restype = _CGPoint
    lib.CGEventCreate.argtypes = [ctypes.c_void_p]
    lib.CGEventCreate.restype = ctypes.c_void_p
    lib.CFRelease.argtypes = [ctypes.c_void_p]
    return lib


def check_permission():
    """True if this process may post synthetic events.

    Uses `AXIsProcessTrusted`, which reports the Accessibility grant without
    prompting. Returns True when the symbol is unavailable rather than
    blocking on an unknown -- a false "no" would be worse than a missed check.
    """
    try:
        lib = _load()
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except (OSError, AttributeError):
        return True


class DarwinPointer(PointerSink):
    """The single macOS system cursor."""

    name = "darwin"
    supports_multi_pointer = False

    def __init__(self):
        self._lib = _load()
        self._buttons_down = set()

    def _current(self):
        event = self._lib.CGEventCreate(None)
        point = self._lib.CGEventGetLocation(event)
        self._lib.CFRelease(event)
        return point

    def _post(self, event_type, point, button):
        event = self._lib.CGEventCreateMouseEvent(None, event_type, point, button)
        if not event:
            raise OSError("CGEventCreateMouseEvent failed")
        self._lib.CGEventPost(_HID_EVENT_TAP, event)
        self._lib.CFRelease(event)

    def move_to(self, x, y):
        # While a button is held, macOS expects DRAGGED rather than MOVED --
        # posting MOVED mid-drag drops the drag in many applications.
        event_type = _LEFT_DRAGGED if _BUTTON_LEFT in self._buttons_down else _MOUSE_MOVED
        self._post(event_type, _CGPoint(float(x), float(y)), _BUTTON_LEFT)

    def move_by(self, dx, dy):
        point = self._current()
        self.move_to(point.x + dx, point.y + dy)

    def press(self, button="left"):
        down, _, code = _BUTTONS.get(button, _BUTTONS["left"])
        self._buttons_down.add(code)
        self._post(down, self._current(), code)

    def release(self, button="left"):
        _, up, code = _BUTTONS.get(button, _BUTTONS["left"])
        self._buttons_down.discard(code)
        self._post(up, self._current(), code)
