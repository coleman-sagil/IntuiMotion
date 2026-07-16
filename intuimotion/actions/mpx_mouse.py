"""Per-hand OS-level cursors via X11 Multi-Pointer X (MPX).

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
"""
import subprocess

from Xlib import X, display
from Xlib.ext import xinput as xi
from Xlib.protocol import rq

from .dry_run import guarded
from .mouse import map_to_screen

_X_XIWarpPointer = 41
_X_XISetClientPointer = 44

# hand type -> MPX master pointer name. Kept to exactly the two hands this
# app tracks -- not a general-purpose N-pointer registry.
_MASTER_NAMES = {"Left": "IntuiMotionLeft", "Right": "IntuiMotionRight"}

_BUTTON_NUMBERS = {"right": 3}  # anything else (including default "left") -> 1


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


def _hand_key(hand_type):
    # Real LeapC hands carry a HandType enum (.name == "Left"/"Right");
    # the tests/fakes.py FakeHand carries a plain "Left"/"Right" string.
    # This normalizes both to the same dict key without caring which one
    # a given caller has.
    return getattr(hand_type, "name", hand_type)


class MpxPointer:
    """One MPX master pointer plus a private X connection whose
    ClientPointer is pinned to it for the lifetime of the connection.
    """

    def __init__(self, name):
        device_name = f"{name} pointer"
        # Best-effort cleanup of a same-named master left behind by an
        # unclean previous exit (e.g. kill -9) before creating a fresh one --
        # not a general stale-device sweep, just self-healing our own name.
        subprocess.run(["xinput", "remove-master", device_name], capture_output=True)
        subprocess.run(["xinput", "create-master", name], check=True, capture_output=True)

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
            dst_x=x,
            dst_y=y,
            deviceid=self.deviceid,
        )
        self._conn.flush()

    def press(self, button):
        self._conn.xtest_fake_input(X.ButtonPress, _BUTTON_NUMBERS.get(button, 1))
        self._conn.flush()

    def release(self, button):
        self._conn.xtest_fake_input(X.ButtonRelease, _BUTTON_NUMBERS.get(button, 1))
        self._conn.flush()

    def close(self):
        self._conn.close()
        subprocess.run(
            ["xinput", "remove-master", str(self.deviceid)], capture_output=True
        )


_pointers = {}


def setup():
    """Create one MPX master pointer per hand. Call once at startup, after
    the X session is up and before the tracking connection opens -- not at
    import time, so importing this module (e.g. under pytest, or headless)
    never touches the real X server or creates master-pointer devices.
    """
    for side, name in _MASTER_NAMES.items():
        _pointers[side] = MpxPointer(name)


def teardown():
    for pointer in _pointers.values():
        pointer.close()
    _pointers.clear()


def _pointer_for(hand_type):
    # Defensive, not just tidy: this runs on the hot per-frame path from a
    # C callback (see connection.py), so a hand_type with no pointer yet
    # (setup() not called, or a hand side setup() doesn't know about) must
    # not raise mid-tracking-loop -- log once and drop the frame instead.
    key = _hand_key(hand_type)
    pointer = _pointers.get(key)
    if pointer is None:
        print(f"[mpx_mouse] no MPX pointer set up for hand {key!r} -- call setup() first")
    return pointer


@guarded(lambda hand_type, x, y: f"move {_hand_key(hand_type)} cursor to ({int(x)}, {int(y)})")
def move_to(hand_type, x, y):
    pointer = _pointer_for(hand_type)
    if pointer is not None:
        pointer.move_to(int(x), int(y))


def move_to_leap_position(hand_type, leap_x, leap_y):
    move_to(hand_type, *map_to_screen(leap_x, leap_y))


@guarded(lambda hand_type, button="left": f"{_hand_key(hand_type)} {button} button down")
def press(hand_type, button="left"):
    pointer = _pointer_for(hand_type)
    if pointer is not None:
        pointer.press(button)


@guarded(lambda hand_type, button="left": f"{_hand_key(hand_type)} {button} button up")
def release(hand_type, button="left"):
    pointer = _pointer_for(hand_type)
    if pointer is not None:
        pointer.release(button)
