"""Per-hand OS-level cursors via X11 Multi-Pointer X (MPX).

Extracted from `mpx_mouse.py` unchanged in behaviour, for one reason: this
file imports `python-Xlib`, which exists only on Linux/X11. While it lived at
the top of `mpx_mouse`, and `pipeline.py` imported `mpx_mouse` at module
scope, IntuiMotion could not be *imported at all* on Windows or macOS -- the
same class of hard-dependency failure the vendor `leap` import caused. Now
`sinks/` imports this lazily, and only after confirming a real X11 session.

Two independent primitives, two independent plumbing paths -- confirmed
live on this machine, not just from docs:

- Motion: XIWarpPointer takes a target deviceid directly, so any X
  connection can move any master pointer without disturbing the others.
  (Confirmed live: warping a second master left the core pointer's queried
  position byte-for-byte unchanged.)
- Buttons: XTestFakeButtonEvent has no per-device targeting at all -- the X
  server delivers it to whichever master is the *issuing connection's*
  ClientPointer (set once via XISetClientPointer), not to any deviceid
  passed by the caller (there isn't one). So each hand gets its own private
  Display connection, with ClientPointer bound once at startup to that
  hand's master -- no per-click toggling, no races between the two hands'
  connections. (Confirmed live: an independent observer window watching for
  ButtonPress/Release received exactly one press+release per connection,
  at the coordinates that connection's master had been warped to.)

Neither XIWarpPointer nor XISetClientPointer is wrapped by python-xlib
(confirmed against Xlib/ext/xinput.py source and python-xlib issue #191) --
both are hand-built requests below on top of Xlib.protocol.rq, wire format
taken from /usr/include/X11/extensions/XI2proto.h, the same pattern
python-xlib's own extension modules use internally.

NOTE: XTest injection is ignored by Wayland compositors. This backend is
selected only for a true X11 session; Wayland gets `sinks/uinput.py`.
"""

import subprocess

from Xlib import X, display
from Xlib.ext import xinput as xi
from Xlib.protocol import rq

from ..sinks.base import PointerSink

_X_XIWarpPointer = 41
_X_XISetClientPointer = 44

# hand type -> MPX master pointer name. Kept to exactly the two hands this
# app tracks -- not a general-purpose N-pointer registry.
MASTER_NAMES = {"Left": "IntuiMotionLeft", "Right": "IntuiMotionRight"}

BUTTON_NUMBERS = {"right": 3}  # anything else (including default "left") -> 1


class _XIWarpPointer(rq.Request):
    _request = rq.Struct(
        rq.Card8("opcode"),
        rq.Opcode(_X_XIWarpPointer),
        rq.RequestLength(),
        rq.Window("src_win"),
        rq.Window("dst_win"),
        xi.FP1616("src_x"),
        xi.FP1616("src_y"),
        rq.Card16("src_width"),
        rq.Card16("src_height"),
        xi.FP1616("dst_x"),
        xi.FP1616("dst_y"),
        xi.DEVICEID("deviceid"),
        rq.Pad(2),
    )


class _XISetClientPointer(rq.Request):
    _request = rq.Struct(
        rq.Card8("opcode"),
        rq.Opcode(_X_XISetClientPointer),
        rq.RequestLength(),
        rq.Window("win"),
        xi.DEVICEID("deviceid"),
        rq.Pad(2),
    )


class MpxPointer(PointerSink):
    """One MPX master pointer plus a private X connection whose
    ClientPointer is pinned to it for the lifetime of the connection.
    """

    name = "x11mpx"
    supports_multi_pointer = True

    def __init__(self, master_name):
        device_name = f"{master_name} pointer"
        # Best-effort cleanup of a same-named master left behind by an
        # unclean previous exit (e.g. kill -9) before creating a fresh one --
        # not a general stale-device sweep, just self-healing our own name.
        subprocess.run(["xinput", "remove-master", device_name], capture_output=True)
        subprocess.run(["xinput", "create-master", master_name], check=True, capture_output=True)

        self._conn = display.Display()
        self._root = self._conn.screen().root
        self._opcode = self._conn.display.get_extension_major(xi.extname)
        self.deviceid = self._resolve_deviceid(device_name)

        _XISetClientPointer(
            display=self._conn.display,
            opcode=self._opcode,
            win=X.NONE,
            deviceid=self.deviceid,
        )
        self._conn.flush()

    def _resolve_deviceid(self, device_name):
        # Take the last match, not the first: if a stale same-named device
        # somehow survived cleanup, the just-created one has the higher id.
        matches = [
            dev.deviceid
            for dev in self._conn.xinput_query_device(xi.AllDevices).devices
            if dev.name == device_name
        ]
        if not matches:
            raise RuntimeError(f"xinput create-master ran but {device_name!r} was not found")
        return matches[-1]

    def move_to(self, x, y):
        _XIWarpPointer(
            display=self._conn.display,
            opcode=self._opcode,
            src_win=X.NONE,
            dst_win=self._root,
            src_x=0,
            src_y=0,
            src_width=0,
            src_height=0,
            dst_x=int(x),
            dst_y=int(y),
            deviceid=self.deviceid,
        )
        self._conn.flush()

    def move_by(self, dx, dy):
        # Same request as move_to, same per-device targeting, one field
        # different: dst_win=X.NONE instead of the root window is what makes
        # the warp relative. "If dest_w is None, XIWarpPointer moves the
        # pointer by the offsets (dest_x, dest_y) relative to the current
        # position of the pointer" -- man 3 XIWarpPointer on this machine
        # (matching XI2proto.h's WarpPointer, where dst_win is a plain
        # Window field with None a legal value).
        #
        # Note the weaker claim than this module's other comments: the
        # relative-motion mechanism is confirmed from the X11 protocol docs,
        # NOT from a live run -- unlike the "confirmed live" notes on
        # XIWarpPointer's per-device targeting and the ClientPointer button
        # plumbing, this path has never been driven by the real Leap sensor.
        _XIWarpPointer(
            display=self._conn.display,
            opcode=self._opcode,
            src_win=X.NONE,
            dst_win=X.NONE,
            src_x=0,
            src_y=0,
            src_width=0,
            src_height=0,
            dst_x=int(round(dx)),
            dst_y=int(round(dy)),
            deviceid=self.deviceid,
        )
        self._conn.flush()

    def press(self, button="left"):
        self._conn.xtest_fake_input(X.ButtonPress, BUTTON_NUMBERS.get(button, 1))
        self._conn.flush()

    def release(self, button="left"):
        self._conn.xtest_fake_input(X.ButtonRelease, BUTTON_NUMBERS.get(button, 1))
        self._conn.flush()

    def close(self):
        self._conn.close()
        subprocess.run(
            ["xinput", "remove-master", str(self.deviceid)], capture_output=True
        )


def build_mpx_pointers(sides=("Left", "Right")):
    """One MPX master pointer per hand side.

    Raises if the X session, the xinput binary, or the XInput2 extension is
    unavailable -- the caller (`sinks.build_pointers`) catches that and falls
    back, so this deliberately does not swallow errors itself.
    """
    built = {}
    try:
        for side in sides:
            built[side] = MpxPointer(MASTER_NAMES[side])
    except Exception:
        # Don't leave half-created master devices behind on a partial failure.
        for pointer in built.values():
            try:
                pointer.close()
            except Exception:  # noqa: BLE001
                pass
        raise
    return built
