"""Screen geometry, per platform.

Pointer mapping needs the size of the coordinate space the sink moves in.
Getting this wrong is a *silent* failure: the cursor still moves, it just
lands in the wrong place, and nothing errors. That is the worst kind of bug
to ship to someone testing on unfamiliar hardware, so each platform gets a
real native query rather than a shared guess.

The coordinate space must match the sink's:
  - Windows: the VIRTUAL DESKTOP (all monitors), matching `win32.py`'s
    SM_CXVIRTUALSCREEN normalization -- not the primary monitor, or a
    second display becomes unreachable.
  - Linux/X11: the RandR virtual desktop, likewise spanning all monitors.
  - macOS: the main display.

`$INTUIMOTION_SCREEN` (e.g. "3840x1080") overrides everything. That is not a
convenience knob -- on Wayland there is no portable way for a client to ask
the compositor for the desktop size, so an explicit override is sometimes
the only correct answer.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

DEFAULT_SIZE = (1920, 1080)

SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


def _from_env():
    raw = os.environ.get("INTUIMOTION_SCREEN", "").strip().lower()
    match = re.fullmatch(r"(\d+)\s*[x,]\s*(\d+)", raw)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def _windows_size():
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        # Match win32.py: become DPI-aware BEFORE querying, or a scaled
        # display reports virtualized (wrong) pixel counts.
        try:
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            try:
                user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass
        width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        if width > 0 and height > 0:
            return int(width), int(height)
    except Exception:  # noqa: BLE001 - detection must never be fatal
        pass
    return None


def _macos_size():
    try:
        import ctypes
        import ctypes.util

        path = ctypes.util.find_library("ApplicationServices")
        if path is None:
            return None
        lib = ctypes.cdll.LoadLibrary(path)
        lib.CGMainDisplayID.restype = ctypes.c_uint32
        lib.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
        lib.CGDisplayPixelsHigh.argtypes = [ctypes.c_uint32]
        display = lib.CGMainDisplayID()
        width = int(lib.CGDisplayPixelsWide(display))
        height = int(lib.CGDisplayPixelsHigh(display))
        if width > 0 and height > 0:
            return width, height
    except Exception:  # noqa: BLE001
        pass
    return None


def _x11_size():
    """Ask Xlib directly. Works on X11 and (via XWayland) usually on Wayland."""
    try:
        from Xlib import display as _display

        screen = _display.Display().screen()
        width, height = int(screen.width_in_pixels), int(screen.height_in_pixels)
        if width > 0 and height > 0:
            return width, height
    except Exception:  # noqa: BLE001
        pass
    return None


def _xrandr_size():
    """RandR's "current W x H" -- the full virtual desktop across monitors.

    Preferred over tkinter's winfo_screenwidth(), which was tried here
    previously and silently reported a single-monitor size (or wasn't
    installed), making a second monitor unreachable in pointer mode.
    """
    try:
        output = subprocess.run(
            ["xrandr", "--query"], capture_output=True, text=True, check=True, timeout=2
        ).stdout
        match = re.search(r"current (\d+) x (\d+)", output)
        if match:
            return int(match.group(1)), int(match.group(2))
    except Exception:  # noqa: BLE001
        pass
    return None


def native_screen_size():
    """Platform-native size, or None if this platform has no native query here.

    Returns None on Linux deliberately: the Linux answer comes from Xlib or
    xrandr, which callers may want to mock or order differently.
    """
    if _from_env():
        return _from_env()
    if sys.platform.startswith("win"):
        return _windows_size()
    if sys.platform == "darwin":
        return _macos_size()
    return None


def screen_size(default=DEFAULT_SIZE):
    """Best available screen size for this machine, never raising."""
    for probe in (native_screen_size, _x11_size, _xrandr_size):
        size = probe()
        if size:
            return size
    return default
