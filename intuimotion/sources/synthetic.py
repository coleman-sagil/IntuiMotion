"""Synthetic hand source -- a scripted gesture performance, no hardware.

This exists so the whole stack (gesture engine, dispatcher, actions, tray
icon, HUD, animations) can be run, demoed, and regression-tested on any
machine with no sensor attached, no vendor daemon, and no driver working.
That matters for three concrete reasons:

  1. The OpenMotion driver currently has an unresolved bulk-transfer
     regression, so live frames are not available -- without this the UI
     cannot be exercised at all.
  2. Cross-platform bring-up (Windows/macOS) needs the UI runnable before
     the driver has been ported to that platform.
  3. A "plug in a USB stick and see it work" demo cannot depend on the
     reviewer owning a specific discontinued sensor.

The choreography below deliberately crosses the real thresholds in
`gestures.py` (open+still for `engage_dwell`, `pinch_strength` past
`pinch_threshold`, `grab_strength` past `grab_threshold`) rather than
emitting arbitrary motion, so what you see is the genuine gesture pipeline
firing -- not a mock of it.
"""

from __future__ import annotations

import math
import time

from .base import RIGHT, Digit, Hand, Palm, Vec3, HandSource

# One full pass of the choreography. Each entry is (label, duration_seconds).
# Kept as data so the timeline is readable at a glance and easy to retune.
SCRIPT = (
    ("absent", 1.0),      # no hand in view -- exercises staleness handling
    ("engage", 1.2),      # open, still hand -> palm_engage (needs 0.4s dwell)
    ("move", 3.0),        # smooth pointer travel
    ("pinch", 0.8),       # pinch past threshold -> left_press
    ("drag", 1.2),        # keep pinching while moving -> drag
    ("release", 0.6),     # pinch releases -> left_release
    ("move", 1.5),
    ("fist", 0.8),        # grab past threshold -> fist_exit back to idle
)

CYCLE_SECONDS = sum(duration for _, duration in SCRIPT)

# Resting palm height, inside gestures.MOUSE_ACTIVE_Y_RANGE (60-180mm) so the
# mouse/touchpad mode is usable too, not just pointer mode.
BASE_Y = 120.0
# Travel amplitude in mm -- comfortably inside a real device's tracking cone.
SPAN_X = 80.0
SPAN_Z = 50.0


def _digits_for(palm_pos, curled):
    """Fingertips laid out around the palm.

    Spacing is deliberately wider than `FINGER_TOGETHER_MAX_GAP` (15mm) so the
    synthetic hand never accidentally reads as a "blade hand" and triggers the
    two-hand minimize-everything gesture. Thumb and middle stay further apart
    than `middle_pinch_distance` (30mm) for the same reason.
    """
    px, py, pz = palm_pos
    reach = 20.0 if curled else 45.0
    extended = not curled
    return {
        "thumb": Digit((px - 38.0, py + 12.0, pz - 8.0), extended),
        "index": Digit((px - 22.0, py + reach, pz - 28.0), extended),
        "middle": Digit((px, py + reach + 4.0, pz - 30.0), extended),
        "ring": Digit((px + 22.0, py + reach, pz - 28.0), extended),
        "pinky": Digit((px + 42.0, py + reach - 8.0, pz - 24.0), extended),
    }


def _beat_at(elapsed):
    """Which scripted beat we are in, and how far through it (0.0-1.0)."""
    t = elapsed % CYCLE_SECONDS
    for label, duration in SCRIPT:
        if t < duration:
            return label, (t / duration if duration else 0.0)
        t -= duration
    return SCRIPT[-1][0], 1.0


def _smoothstep(a):
    """Ease-in/out so synthetic motion looks like a hand, not a sawtooth --
    and, more practically, so velocity stays below STILL_SPEED_MAX during the
    engage beat instead of spiking at beat boundaries."""
    a = max(0.0, min(1.0, a))
    return a * a * (3.0 - 2.0 * a)


def hand_for(elapsed, hand_type=RIGHT):
    """The scripted hand at `elapsed` seconds, or None when none is in view.

    Pure function of time, with no state and no I/O, which is what makes the
    choreography directly unit-testable (see tests/test_sources.py).
    """
    beat, progress = _beat_at(elapsed)
    if beat == "absent":
        return None

    moving = beat in ("move", "drag")
    if moving:
        # Lissajous-ish travel: distinct X and Z frequencies so the path is a
        # visible curve rather than a straight line retraced.
        phase = elapsed * 1.1
        x = math.sin(phase) * SPAN_X
        z = math.cos(phase * 0.7) * SPAN_Z
        # Analytic derivative -> honest velocity, so speed-gated gestures
        # (swipes, stillness) see physically consistent numbers.
        vx = math.cos(phase) * SPAN_X * 1.1
        vz = -math.sin(phase * 0.7) * SPAN_Z * 0.77
    else:
        # Held still: the engage beat depends on speed < STILL_SPEED_MAX.
        x = math.sin(elapsed * 0.0) * 0.0
        z = 0.0
        vx = vz = 0.0

    y = BASE_Y
    palm_pos = (x, y, z)

    pinch = 0.0
    grab = 0.0
    if beat == "pinch":
        pinch = _smoothstep(progress)          # ramps through 0.85 threshold
    elif beat == "drag":
        pinch = 1.0                            # held closed while moving
    elif beat == "release":
        pinch = 1.0 - _smoothstep(progress)    # falls back through threshold
    elif beat == "fist":
        grab = _smoothstep(progress)

    curled = grab > 0.5 or pinch > 0.5
    return Hand(
        hand_type=hand_type,
        palm=Palm(position=palm_pos, velocity=Vec3(vx, 0.0, vz)),
        pinch_strength=pinch,
        grab_strength=grab,
        digits=_digits_for(palm_pos, curled),
    )


class SyntheticSource(HandSource):
    """Emits the scripted choreography at a steady frame rate."""

    name = "synthetic"

    def __init__(self, on_hand_frame, on_tracking_frame=None, fps=60.0, hand_type=RIGHT):
        super().__init__(on_hand_frame, on_tracking_frame)
        self.fps = float(fps)
        self.hand_type = hand_type

    def _startup(self):
        print(
            f"[source:synthetic] no hardware needed -- replaying a "
            f"{CYCLE_SECONDS:.1f}s scripted gesture loop at {self.fps:.0f} fps"
        )

    def _produce(self):
        period = 1.0 / self.fps
        started = time.monotonic()
        next_tick = started
        while not self.stopped:
            now = time.monotonic()
            hand = hand_for(now - started, self.hand_type)
            # An empty list is a real, meaningful frame: it is how the
            # pipeline learns a hand left the tracking volume and releases
            # any stale held mouse button.
            self.emit([hand] if hand is not None else [])
            next_tick += period
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                # Fell behind (slow machine / debugger): resync rather than
                # spiral into an ever-growing backlog of catch-up frames.
                next_tick = time.monotonic()
