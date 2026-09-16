"""Platform-appropriate pointer sinks.

`build_pointers()` picks a backend and returns one sink per hand. Selection
order: explicit argument, then `$INTUIMOTION_INPUT`, then auto-detection.

Auto-detection order and why
----------------------------
Windows  -> win32        the only option; native SendInput
macOS    -> darwin       the only option; Quartz CGEvent
Linux    -> x11mpx       ONLY on a real X11 session, because it is the one
                         backend that gives each hand an independent OS
                         cursor, which is a genuine product feature
         -> uinput       otherwise, including every Wayland session --
                         XTest/MPX injection is not honoured by Wayland
                         compositors, so on Wayland this is the only Linux
                         path that works at all
         -> null         if uinput is not permitted (no udev rule yet)

Detecting Wayland via `$WAYLAND_DISPLAY`/`$XDG_SESSION_TYPE` matters: on a
Wayland session XWayland still sets `$DISPLAY`, so "DISPLAY is set" is NOT
evidence that XTest injection will work. That single check is the difference
between a working cursor and a silently dead one on a modern Linux desktop.

Every backend is standard-library only (ctypes against the OS), so supporting
a platform never adds a third-party dependency.
"""

from __future__ import annotations

import os
import sys

from .base import PointerSink
from .null import NullPointer

__all__ = ["PointerSink", "NullPointer", "build_pointers", "detect_backend", "BACKENDS"]

BACKENDS = ("x11mpx", "uinput", "win32", "darwin", "null")

#: Hand sides that get their own sink where the platform supports it.
HAND_SIDES = ("Left", "Right")


def _is_wayland():
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def detect_backend():
    """Best backend for this machine, as a name from `BACKENDS`."""
    if sys.platform.startswith("win"):
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        # MPX only where XTest is actually honoured -- i.e. a true X session.
        if os.environ.get("DISPLAY") and not _is_wayland():
            return "x11mpx"
        return "uinput"
    return "null"


def resolve_backend(name=None):
    return (name or os.environ.get("INTUIMOTION_INPUT") or detect_backend()).strip().lower()


def _build_one(backend):
    """Construct a single sink for `backend`, or raise."""
    if backend == "win32":
        from .win32 import Win32Pointer

        return Win32Pointer()
    if backend == "darwin":
        from .darwin import check_permission, DarwinPointer

        if not check_permission():
            raise PermissionError(
                "macOS Accessibility permission is not granted, so synthetic "
                "input would be silently ignored. Grant it under System "
                "Settings -> Privacy & Security -> Accessibility."
            )
        return DarwinPointer()
    if backend == "uinput":
        from .uinput import UinputPointer

        return UinputPointer()
    if backend == "null":
        return NullPointer(verbose=True)
    raise ValueError(f"unknown input backend {backend!r}; available: {', '.join(BACKENDS)}")


def build_pointers(backend=None, sides=HAND_SIDES):
    """Return `{side: sink}` for every hand, using the selected backend.

    On single-cursor platforms every side maps to the SAME sink object, so
    both hands drive the one system cursor. That is shared deliberately
    rather than silently creating two virtual devices that fight each other.

    Falls back to `null` (with an explanation) instead of raising, so an
    unconfigured machine still runs the whole gesture stack.
    """
    backend = resolve_backend(backend)

    if backend == "x11mpx":
        # Imported here, not at module scope: python-Xlib is Linux/X11-only,
        # and importing it on Windows is an immediate ImportError.
        from ..actions.x11_mpx import build_mpx_pointers

        try:
            pointers = build_mpx_pointers(sides)
            print("[sinks] x11mpx: one independent OS cursor per hand")
            return pointers
        except Exception as error:  # noqa: BLE001 - fall back, never hard-fail
            print(f"[sinks] x11mpx unavailable ({error}); falling back to uinput")
            backend = "uinput"

    try:
        sink = _build_one(backend)
    except Exception as error:  # noqa: BLE001
        print(f"[sinks] {backend} unavailable ({error}); falling back to null sink")
        sink = NullPointer(verbose=True)

    if not sink.supports_multi_pointer and len(sides) > 1:
        print(
            f"[sinks] {sink.name}: one system cursor, shared by both hands "
            "(only X11/MPX supports a cursor per hand)"
        )
    return {side: sink for side in sides}
