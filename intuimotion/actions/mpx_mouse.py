"""Per-hand pointer routing, on whatever the host OS actually supports.

This module owns the *routing* -- which hand's gesture drives which cursor,
and the Leap-units-to-pixels conversion. The platform-specific injection
lives in `intuimotion/sinks/`, one backend per OS, all standard-library
ctypes.

Why the split (this was a real, load-bearing bug)
-------------------------------------------------
This module used to `import Xlib` at the top, and `pipeline.py` imports this
module at the top. python-Xlib is Linux/X11-only, so on Windows or macOS
`import intuimotion.pipeline` raised ImportError and the entire application
was unrunnable -- exactly the failure the vendor `import leap` caused on the
input side. The X11 code now lives in `actions/x11_mpx.py` and is imported
only after `sinks` confirms a real X11 session.

The name is kept for continuity; it is no longer MPX-specific. MPX remains
the only backend that gives each hand its own independent OS cursor, and it
is still preferred on X11 for exactly that reason -- every other platform has
a single system cursor that both hands share.
"""

from ..sinks import build_pointers
from .dry_run import guarded
from .mouse import MOUSE_SENSITIVITY, map_to_screen

# Re-exported for continuity: tests and older call sites read this. The X11
# backend owns the authoritative copy.
_BUTTON_NUMBERS = {"right": 3}  # anything else (including default "left") -> 1

_pointers = {}

#: Name of the backend actually in use, set by setup(). Useful in logs and
#: for the UI to report what the machine is capable of.
active_backend = None


def _hand_key(hand_type):
    # Real LeapC hands carry a HandType enum (.name == "Left"/"Right");
    # a source-built Hand (and tests/fakes.py) carries a plain string.
    # This normalizes both to the same dict key without caring which one
    # a given caller has.
    return getattr(hand_type, "name", hand_type)


def setup(backend=None):
    """Create one pointer sink per hand for this platform.

    Call once at startup, after the display session is up and before the
    tracking source opens -- not at import time, so importing this module
    (e.g. under pytest, or headless) never touches the real display server
    or creates virtual input devices.

    Never raises on an unsupported/unpermitted platform: `sinks` falls back
    to a logging sink so the gesture stack still runs end to end.
    """
    global active_backend
    _pointers.update(build_pointers(backend))
    some = next(iter(_pointers.values()), None)
    active_backend = getattr(some, "name", None)


def teardown():
    # On single-cursor platforms every side maps to the SAME sink object, so
    # close each distinct object once rather than once per hand.
    for pointer in {id(p): p for p in _pointers.values()}.values():
        try:
            pointer.close()
        except Exception as error:  # noqa: BLE001 - teardown must not raise
            print(f"[mpx_mouse] error closing {getattr(pointer, 'name', '?')}: {error}")
    _pointers.clear()


def _pointer_for(hand_type):
    # Defensive, not just tidy: this runs on the hot per-frame path from the
    # source's callback thread, so a hand_type with no pointer yet (setup()
    # not called, or a hand side setup() doesn't know about) must not raise
    # mid-tracking-loop -- log once and drop the frame instead.
    key = _hand_key(hand_type)
    pointer = _pointers.get(key)
    if pointer is None:
        print(f"[mpx_mouse] no pointer set up for hand {key!r} -- call setup() first")
    return pointer


@guarded(lambda hand_type, x, y: f"move {_hand_key(hand_type)} cursor to ({int(x)}, {int(y)})")
def move_to(hand_type, x, y):
    pointer = _pointer_for(hand_type)
    if pointer is not None:
        pointer.move_to(int(x), int(y))


def move_to_leap_position(hand_type, leap_x, leap_y):
    move_to(hand_type, *map_to_screen(leap_x, leap_y))


@guarded(
    lambda hand_type, dx, dy: (
        f"move {_hand_key(hand_type)} cursor by ({int(round(dx))}, {int(round(dy))})"
    )
)
def move_by(hand_type, dx, dy):
    pointer = _pointer_for(hand_type)
    if pointer is not None:
        pointer.move_by(int(round(dx)), int(round(dy)))


def move_by_leap_delta(hand_type, dx_mm, dz_mm):
    """Mode.MOUSE counterpart to move_to_leap_position, per hand cursor.

    MOUSE_SENSITIVITY and the dz sign convention are deliberately mouse.py's,
    imported rather than redefined here -- one source of truth for the tuning
    constant, the same way map_to_screen is shared for the absolute case, so
    tuning either number moves both cursor paths together and the single-
    cursor and MPX paths can't silently drift apart.
    """
    move_by(hand_type, dx_mm * MOUSE_SENSITIVITY, dz_mm * MOUSE_SENSITIVITY)


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
