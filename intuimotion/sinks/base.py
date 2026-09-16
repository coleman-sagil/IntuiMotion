"""Pointer sink protocol -- where gesture output actually lands.

`sources/` is the input plane (any sensor -> normalized `Hand`). This is the
output plane (pointer intent -> the host OS). Keeping them as two separate,
narrow protocols is what lets a device port and a platform port happen
independently of each other.

Every backend implements the same five methods, which are exactly the surface
`actions/mpx_mouse.py` already drove against an X11 MPX master pointer:

    move_to(x, y)        absolute, in screen pixels
    move_by(dx, dy)      relative, in screen pixels
    press(button)        "left" | "right"
    release(button)
    close()

Backends are pure standard library -- `ctypes` against the platform's own
native API -- so adding a platform adds no third-party dependency. That is
deliberate: the vendor SDK that had to be removed from the input plane was a
third-party dependency that died, and the same failure mode applies to input
injection libraries.

Multi-pointer is a capability, not an assumption. X11 with MPX gives each
hand its own real OS cursor; Windows, macOS and Linux/uinput have exactly one
system cursor, so both hands share it. `supports_multi_pointer` lets callers
tell the difference honestly instead of silently pretending two cursors exist.
"""

from __future__ import annotations


class PointerSink:
    """Base class for a pointer backend. See module docstring."""

    #: Backend name, for logs and diagnostics.
    name = "base"

    #: True only where each hand can drive an independent OS cursor.
    supports_multi_pointer = False

    def move_to(self, x, y):
        raise NotImplementedError

    def move_by(self, dx, dy):
        raise NotImplementedError

    def press(self, button="left"):
        raise NotImplementedError

    def release(self, button="left"):
        raise NotImplementedError

    def close(self):
        """Release any OS resources. Must be safe to call more than once."""


def clamp(value, low, high):
    return max(low, min(high, value))
