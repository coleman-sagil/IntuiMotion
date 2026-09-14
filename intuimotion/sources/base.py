"""Device-agnostic hand/pose schema and source protocol.

This module is the seam that lets IntuiMotion run on *any* sensing device
rather than only an UltraLeap one. Nothing here imports a vendor SDK, a
tracking library, or any third-party package -- it is pure standard library,
on purpose, because every device backend and every platform has to be able to
import it.

Why these exact field names
---------------------------
The gesture engine (`intuimotion.gestures`) was originally written directly
against LeapC's datatypes, so it reads `hand.palm.position`,
`hand.index.distal.next_joint`, `hand.pinch_strength`, and so on. Rather than
rewrite the (already working, already tested) gesture logic, the schema here
reproduces that shape exactly. That makes this a genuine abstraction boundary
instead of a rewrite: a stereo-IR device, a webcam + pose model, a LiDAR or
radar frontend all just have to emit these fields, and every gesture, action
and UI above keeps working untouched.

`tests/fakes.py` documents the same contract for the test suite; the classes
here are the runtime equivalent, and `tests/test_sources.py` asserts the two
stay compatible.

Units and axes (inherited from the LeapC convention the gesture thresholds
were tuned against -- do not change these without retuning `gestures.py`):
  - positions and joint coordinates are millimetres
  - velocities are millimetres/second
  - +x is right, +y is up (away from the device), -z is away from the user
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

# Digit order matters: several call sites iterate digits positionally.
DIGIT_NAMES = ("thumb", "index", "middle", "ring", "pinky")

LEFT = "Left"
RIGHT = "Right"


class Vec3(tuple):
    """A 3D point/vector.

    Subclasses `tuple` so it works both as `v.x` (how `gestures.py` reads
    joint positions) and as `vx, vy, vz = v` (how `pipeline.py` unpacks
    velocity). Matching both access styles is why this isn't a dataclass.
    """

    __slots__ = ()

    def __new__(cls, x=0.0, y=0.0, z=0.0):
        return super().__new__(cls, (float(x), float(y), float(z)))

    @property
    def x(self):
        return self[0]

    @property
    def y(self):
        return self[1]

    @property
    def z(self):
        return self[2]

    def __repr__(self):
        return f"Vec3({self[0]:.1f}, {self[1]:.1f}, {self[2]:.1f})"


class Bone:
    """One bone segment. Only `next_joint` (the distal end) is consumed today,
    but the class exists so backends that *do* have full bone data have an
    obvious place to put it rather than inventing a parallel shape."""

    __slots__ = ("prev_joint", "next_joint")

    def __init__(self, next_joint=(0.0, 0.0, 0.0), prev_joint=(0.0, 0.0, 0.0)):
        self.next_joint = next_joint if isinstance(next_joint, Vec3) else Vec3(*next_joint)
        self.prev_joint = prev_joint if isinstance(prev_joint, Vec3) else Vec3(*prev_joint)


class Digit:
    """One finger. `distal.next_joint` is the fingertip -- that is the point
    the pinch/steeple gestures measure between."""

    __slots__ = ("distal", "is_extended")

    def __init__(self, tip=(0.0, 0.0, 0.0), is_extended=False):
        self.distal = Bone(tip)
        self.is_extended = bool(is_extended)

    @property
    def tip(self):
        return self.distal.next_joint


class Palm:
    __slots__ = ("position", "velocity")

    def __init__(self, position=(0.0, 0.0, 0.0), velocity=(0.0, 0.0, 0.0)):
        self.position = position if isinstance(position, Vec3) else Vec3(*position)
        self.velocity = velocity if isinstance(velocity, Vec3) else Vec3(*velocity)


class Hand:
    """One tracked hand, in the normalized schema every backend emits.

    `type` is a plain `"Left"`/`"Right"` string rather than an enum so it
    survives a Qt signal and needs no vendor type to construct.
    `mpx_mouse._hand_key` already falls back to the value itself when there is
    no `.name`, so plain strings work throughout unchanged.
    """

    __slots__ = ("type", "palm", "pinch_strength", "grab_strength") + DIGIT_NAMES

    def __init__(
        self,
        hand_type=RIGHT,
        palm=None,
        pinch_strength=0.0,
        grab_strength=0.0,
        digits=None,
    ):
        self.type = hand_type
        self.palm = palm if palm is not None else Palm()
        self.pinch_strength = float(pinch_strength)
        self.grab_strength = float(grab_strength)
        digits = digits or {}
        for name in DIGIT_NAMES:
            setattr(self, name, digits.get(name) or Digit())

    @property
    def digits(self):
        return [getattr(self, name) for name in DIGIT_NAMES]

    def __repr__(self):
        return (
            f"<Hand {self.type} pinch={self.pinch_strength:.2f} "
            f"grab={self.grab_strength:.2f} palm={self.palm.position!r}>"
        )


class HandSource:
    """Base class for anything that produces hand frames.

    Subclasses implement `_produce()`, which runs on a background thread and
    calls `self.emit(hands)` once per frame. The public surface deliberately
    mirrors the shape `main.run()` already used for the vendor connection
    (`.open()` as a context manager, `.set_tracking_mode()`), so swapping
    backends needs no restructuring of the run loop.

    Threading: `emit` is called from the producer thread, exactly as the
    vendor SDK called its callbacks from its own thread. `UiBridge` is
    constructed on the GUI thread and so Qt queues those signals across
    automatically -- the same guarantee that already held before.
    """

    #: Human-readable backend name, shown in logs and the tray tooltip.
    name = "base"

    def __init__(self, on_hand_frame, on_tracking_frame=None):
        self._on_hand_frame = on_hand_frame
        self._on_tracking_frame = on_tracking_frame
        self._stop = threading.Event()
        self._thread = None

    # -- subclass hooks ---------------------------------------------------
    def _produce(self):
        """Generate frames until `self._stop` is set. Must call `self.emit()`."""
        raise NotImplementedError

    def _startup(self):
        """Optional: acquire the device. Raise to abort `open()`."""

    def _shutdown(self):
        """Optional: release the device. Always called, even on error."""

    # -- plumbing ---------------------------------------------------------
    def emit(self, hands):
        """Deliver one frame's worth of hands to the pipeline."""
        for hand in hands:
            self._on_hand_frame(hand)
        if self._on_tracking_frame is not None:
            self._on_tracking_frame(hands)

    def set_tracking_mode(self, mode="desktop"):
        """No-op by default.

        Only the vendor backend ever had a real tracking-mode concept; it is
        kept on the base class so the run loop does not need a backend check.
        """

    @property
    def stopped(self):
        return self._stop.is_set()

    @contextmanager
    def open(self):
        self._startup()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_guarded, name=f"{self.name}-source", daemon=True
        )
        self._thread.start()
        try:
            yield self
        finally:
            self.close()

    def _run_guarded(self):
        try:
            self._produce()
        except Exception as error:  # noqa: BLE001 - a backend crash must not kill the app
            print(f"[source:{self.name}] stopped: {error}")

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._shutdown()
