"""Windows pointer backend -- native `SendInput`, via ctypes only.

No third-party package: this talks straight to `user32.dll`, the same API
every Windows automation library wraps. That keeps the Windows port free of
another dependency that could be abandoned the way the vendor SDK was.

Coordinate model (the part that is easy to get wrong)
-----------------------------------------------------
`SendInput` with `MOUSEEVENTF_ABSOLUTE` does NOT take pixels. It takes a
normalized 0..65535 coordinate across the target rectangle, and which
rectangle depends on a second flag:

  - without `MOUSEEVENTF_VIRTUALDESK` the range spans the PRIMARY monitor,
  - with it, the range spans the whole VIRTUAL DESKTOP (all monitors).

We use the virtual desktop, so a multi-monitor setup works, and convert
pixels ourselves against `SM_XVIRTUALSCREEN`/`SM_CXVIRTUALSCREEN`. The
`+ 1` in the denominator and the rounding are what make the far edge of the
screen actually reachable rather than one pixel short.

DPI: we call `SetProcessDpiAwarenessContext` where available so
`GetSystemMetrics` reports real pixels instead of virtualized ones on a
scaled display. Without it, cursor position drifts on any HiDPI laptop --
which is exactly what a modern ThinkPad is.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from .base import PointerSink, clamp

# --- constants (winuser.h) -------------------------------------------------
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
_DPI_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

_BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        # Pointer-sized: must be ULONG_PTR, not DWORD, or the struct is the
        # wrong size on 64-bit and SendInput silently rejects every event.
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


def _enable_dpi_awareness(user32):
    """Best effort: old Windows builds lack the call, which is not fatal."""
    try:
        user32.SetProcessDpiAwarenessContext(_DPI_PER_MONITOR_AWARE_V2)
    except (AttributeError, OSError):
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


class Win32Pointer(PointerSink):
    """The single Windows system cursor.

    Windows has one cursor, so every hand shares this sink -- hence
    `supports_multi_pointer = False`. Two hands both driving it will fight;
    callers that care should route only one hand to it.
    """

    name = "win32"
    supports_multi_pointer = False

    def __init__(self):
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        _enable_dpi_awareness(self._user32)
        self._user32.SendInput.argtypes = (
            wintypes.UINT,
            ctypes.POINTER(_INPUT),
            ctypes.c_int,
        )
        self._user32.SendInput.restype = wintypes.UINT
        self._refresh_virtual_screen()

    def _refresh_virtual_screen(self):
        metric = self._user32.GetSystemMetrics
        self.origin_x = metric(SM_XVIRTUALSCREEN)
        self.origin_y = metric(SM_YVIRTUALSCREEN)
        # Guard against a 0 width/height (can happen very early at logon):
        # it would make the normalization divide by zero.
        self.width = max(1, metric(SM_CXVIRTUALSCREEN))
        self.height = max(1, metric(SM_CYVIRTUALSCREEN))

    def _send(self, flags, dx=0, dy=0):
        event = _INPUT(
            type=INPUT_MOUSE,
            union=_INPUTUNION(
                mi=_MOUSEINPUT(
                    dx=int(dx), dy=int(dy), mouseData=0, dwFlags=flags, time=0,
                    dwExtraInfo=None,
                )
            ),
        )
        sent = self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT))
        if sent != 1:
            raise OSError(
                f"SendInput rejected the event (error {ctypes.get_last_error()})"
            )

    def _normalize(self, x, y):
        """Screen pixels -> the 0..65535 absolute range, virtual-desktop based."""
        rel_x = clamp(int(x) - self.origin_x, 0, self.width - 1)
        rel_y = clamp(int(y) - self.origin_y, 0, self.height - 1)
        return (
            int(round(rel_x * 65535.0 / (self.width - 1 or 1))),
            int(round(rel_y * 65535.0 / (self.height - 1 or 1))),
        )

    def move_to(self, x, y):
        nx, ny = self._normalize(x, y)
        self._send(
            MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny
        )

    def move_by(self, dx, dy):
        # Relative motion is plain pixels and is subject to the user's pointer
        # acceleration curve -- unlike the absolute path, which is not.
        self._send(MOUSEEVENTF_MOVE, int(round(dx)), int(round(dy)))

    def press(self, button="left"):
        self._send(_BUTTON_FLAGS.get(button, _BUTTON_FLAGS["left"])[0])

    def release(self, button="left"):
        self._send(_BUTTON_FLAGS.get(button, _BUTTON_FLAGS["left"])[1])
