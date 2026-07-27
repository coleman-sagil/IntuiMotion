"""Screen calibration via the two-hand boundary-tracing ritual (Matthew,
2026-07-27, revising the single-hand ray-walking technique in
calibration.py): hold both pointer fingers out at the two top corners
until locked in place, then trace both fingers down along the screen's
real physical edges (assumed to stay on/near the surface, per the
original "pointer fingers touching the screen corners" framing) to the
bottom corners, holding still again at the bottom to lock the end point.

Recommended over calibration.py's ScreenCalibrator for any case where the
user can physically touch/trace the screen (MONITOR, TV) -- this measures
each edge's corners *directly*, as real 3D positions, rather than as an
ambiguous ray needing the known-size hack calibration.py requires (see
that module's docstring for why that hack was necessary there). Keep
calibration.py's approach around for later non-touch scenarios (e.g. a
future AR mode with no physical surface to trace) rather than deleting it
-- it solves a genuinely different problem (position from a ray with no
scale) than this module does (position measured directly).

Deliberately sensor-agnostic like calibration.py: takes plain
(is_pointing, position, now) per hand, not LeapC hand objects.

NEEDS REAL-WORLD VALIDATION (2026-07-27): correct against synthetic data
(tests/test_boundary_calibration.py) but every dwell/speed/span threshold
below is an untuned starting point, same status as calibration.py's.
"""
import numpy as np

from .screen_modes import ScreenMode, require_implemented


def _speed(p1, p2, dt):
    if dt <= 0:
        return 0.0
    return float(np.linalg.norm(np.asarray(p2) - np.asarray(p1)) / dt)


class EdgeTracer:
    """One hand tracing one screen edge, top corner to bottom corner.

    Three phases, gated on the same "pointing pose held still" signal used
    elsewhere in this codebase for deliberate confirmation (mirrors
    GestureInterpreter's palm_engage: "open, still hand held" -- here,
    "pointing, still hand held"). No fist gesture anywhere in this ritual;
    hold-still is the one confirmation signal, reused at both ends.

    1. WAITING_FOR_START_LOCK: hold the pointing pose still at the top
       corner for HOLD_DWELL seconds -> locks the start corner's position,
       begins tracing.
    2. TRACING: move the still-pointing finger down the edge; every sample
       is recorded. Holding still again for HOLD_DWELL seconds, but only
       once at least MIN_TRACE_SPAN_MM away from the start point (guards
       against the natural stillness right after the start-lock itself
       immediately re-triggering an end-lock), ends the trace.
    3. DONE: start_point, end_point, and the full trace_points path are
       available.

    Losing the pointing pose at any point before DONE resets all progress
    for this hand -- same "don't keep a broken trajectory" principle as
    calibration.py's CornerCollector.
    """

    HOLD_DWELL = 0.4  # seconds -- matches the existing palm_engage dwell
    STILL_SPEED_MAX_MM_S = 30.0  # tighter than gestures.py's STILL_SPEED_MAX
    # (150 mm/s) since this needs a precise position lock, not just
    # "roughly not moving"
    MIN_TRACE_SPAN_MM = 100.0

    WAITING_FOR_START_LOCK = "waiting_for_start_lock"
    TRACING = "tracing"
    DONE = "done"

    def __init__(self):
        self.state = self.WAITING_FOR_START_LOCK
        self.start_point = None
        self.end_point = None
        self.trace_points = []
        self._still_since = None
        self._last_position = None
        self._last_time = None

    @property
    def is_done(self):
        return self.state == self.DONE

    def update(self, is_pointing, position, now):
        if self.state == self.DONE:
            return

        if not is_pointing:
            self._reset_progress()
            return

        position = np.asarray(position, dtype=float)
        speed = 0.0
        if self._last_position is not None and self._last_time is not None:
            speed = _speed(self._last_position, position, now - self._last_time)
        self._last_position = position
        self._last_time = now
        is_still = speed <= self.STILL_SPEED_MAX_MM_S

        if self.state == self.WAITING_FOR_START_LOCK:
            if is_still:
                if self._still_since is None:
                    self._still_since = now
                if now - self._still_since >= self.HOLD_DWELL:
                    self.start_point = position.copy()
                    self.trace_points = [position.copy()]
                    self.state = self.TRACING
                    self._still_since = None
            else:
                self._still_since = None

        elif self.state == self.TRACING:
            self.trace_points.append(position.copy())
            far_enough = np.linalg.norm(position - self.start_point) >= self.MIN_TRACE_SPAN_MM
            if is_still and far_enough:
                if self._still_since is None:
                    self._still_since = now
                if now - self._still_since >= self.HOLD_DWELL:
                    self.end_point = position.copy()
                    self.state = self.DONE
            else:
                self._still_since = None

    def _reset_progress(self):
        self.state = self.WAITING_FOR_START_LOCK
        self.start_point = None
        self.end_point = None
        self.trace_points = []
        self._still_since = None
        self._last_position = None
        self._last_time = None

    def fitted_line(self):
        """Least-squares (PCA) refinement of the traced edge: fits a
        straight line through all trace_points (which includes noisy
        real-hand-tremor wobble, not just start/end), then returns
        (refined_start, refined_end) by projecting the raw start/end onto
        that fitted line. Reduces noise vs. trusting the two raw locked
        points alone. Call only when is_done.
        """
        pts = np.array(self.trace_points)
        centroid = pts.mean(axis=0)
        _, _, vh = np.linalg.svd(pts - centroid)
        direction = vh[0]
        start_t = np.dot(self.start_point - centroid, direction)
        end_t = np.dot(self.end_point - centroid, direction)
        refined_start = centroid + start_t * direction
        refined_end = centroid + end_t * direction
        return refined_start, refined_end


class BoundaryCalibrationResult:
    def __init__(self, mode, corners):
        self.mode = mode
        self.corners = corners  # dict: corner name -> np.array([x, y, z])

    def to_screen_uv(self, point):
        """Same projection as calibration.ScreenCalibration.to_screen_uv:
        (0,0)=top_left, (1,0)=top_right, (0,1)=bottom_left, (1,1)=bottom_right.
        """
        tl = self.corners["top_left"]
        tr = self.corners["top_right"]
        bl = self.corners["bottom_left"]
        u_axis = tr - tl
        v_axis = bl - tl
        rel = np.asarray(point, dtype=float) - tl
        u = np.dot(rel, u_axis) / np.dot(u_axis, u_axis)
        v = np.dot(rel, v_axis) / np.dot(v_axis, v_axis)
        return float(u), float(v)


class BoundaryCalibrator:
    """Orchestrates both hands' EdgeTracers (left hand: top_left ->
    bottom_left, right hand: top_right -> bottom_right) and produces a
    BoundaryCalibrationResult once both are done.
    """

    def __init__(self, mode=ScreenMode.MONITOR, on_complete=None, use_fitted_line=True):
        require_implemented(mode)
        self.mode = mode
        self.use_fitted_line = use_fitted_line
        self.on_complete = on_complete
        self.left = EdgeTracer()
        self.right = EdgeTracer()
        self._result = None
        self._on_complete_fired = False

    @property
    def is_complete(self):
        return self.left.is_done and self.right.is_done

    @property
    def result(self):
        """Computed lazily from self.left/self.right, not push-updated --
        deliberately robust to however the two EdgeTracers actually get
        driven (directly, or via update_left_hand/update_right_hand
        below), rather than requiring every caller to go through one
        specific method or risk a silently-stuck None. Cached once both
        hands are done, since EdgeTracer state doesn't change further
        after is_done.
        """
        if not self.is_complete:
            return None
        if self._result is None:
            if self.use_fitted_line:
                top_left, bottom_left = self.left.fitted_line()
                top_right, bottom_right = self.right.fitted_line()
            else:
                top_left, bottom_left = self.left.start_point, self.left.end_point
                top_right, bottom_right = self.right.start_point, self.right.end_point
            corners = {
                "top_left": top_left,
                "top_right": top_right,
                "bottom_left": bottom_left,
                "bottom_right": bottom_right,
            }
            self._result = BoundaryCalibrationResult(mode=self.mode, corners=corners)
        if self.on_complete and not self._on_complete_fired:
            self._on_complete_fired = True
            self.on_complete(self._result)
        return self._result

    def update_left_hand(self, is_pointing, position, now):
        if not self.left.is_done:
            self.left.update(is_pointing, position, now)

    def update_right_hand(self, is_pointing, position, now):
        if not self.right.is_done:
            self.right.update(is_pointing, position, now)
