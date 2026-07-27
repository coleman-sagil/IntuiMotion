"""Screen calibration via the corner-pointing ritual (Matthew, 2026-07-27):
point at a screen corner, walk backward while staying pointed at it, close
a fist to solidify that corner, repeat for all 4 corners in order, then
solve for the screen's plane and corner points in Leap-space.

Covers ScreenMode.MONITOR and ScreenMode.TV (both flat rectangular
screens, geometrically identical calibration problem) -- see
screen_modes.py. Deliberately sensor-agnostic: this module takes plain
(is_pointing, fingertip_position, is_fist) tuples, not LeapC hand objects,
so it's testable without FakeHand/real bindings at all. gestures.py's
is_pointing_pose() plus the existing grab_strength/grab_threshold pattern
is what a caller uses to derive that tuple from a real hand each frame.

NEEDS REAL-WORLD VALIDATION (2026-07-27): the geometry below is correct
for clean/synthetic input (see tests/test_calibration.py, which checks it
against known ground-truth rectangles) but every threshold and the t0
initial guess in solve_screen_plane are untuned defaults, the same
"confirmed correct against synthetic data, not yet against real hand
noise" status IntuiMotion's own gesture thresholds started at. Don't
treat this as validated until it's actually run against a real
calibration session.

IMPORTANT, discovered via testing, not assumed: "4 rays + right angles +
equal opposite sides + coplanar" is NOT enough to uniquely determine the
rectangle -- confirmed empirically that a second, different-sized,
different-position rectangle can satisfy those same relative-shape
constraints with equally-zero residual, for the same 4 rays. The scale/
position ambiguity is real, not a solver bug. solve_screen_plane requires
the screen's actual known width/height (in mm) as a hard constraint to
resolve it -- anyone can measure a monitor/TV, so this is a reasonable
ask, not a limitation worth working around blindly.
"""
import numpy as np
from scipy.optimize import least_squares

from .screen_modes import ScreenMode, require_implemented

CORNER_ORDER = ("top_left", "top_right", "bottom_right", "bottom_left")


class CalibrationState:
    WAITING_TO_POINT = "waiting_to_point"
    COLLECTING = "collecting"
    DONE = "done"


class CalibrationRay:
    """A 3D line, in Leap-space, believed to pass through one screen
    corner. `direction` points from the walked-out position back toward
    the corner (positive t along it moves toward the corner from `origin`).
    """

    def __init__(self, origin, direction):
        self.origin = np.asarray(origin, dtype=float)
        self.direction = np.asarray(direction, dtype=float)

    def point_at(self, t):
        return self.origin + t * self.direction


class CornerCollector:
    """Collects a fingertip-position trajectory while the pointing pose is
    held, and fits a 3D ray through those samples on "solidify" (fist).
    Multiple samples along the same aim, taken from different physical
    positions as the user steps back, let the ray be fit via least-squares
    (PCA) instead of relying on one frame's noisy fingertip position.
    """

    MIN_SAMPLES_TO_SOLIDIFY = 5
    MIN_SPAN_MM = 50.0  # samples must span at least this much distance, or
    # "walk out" never really happened and a ray fit would be degenerate

    def __init__(self):
        self._samples = []

    def add_sample(self, position):
        self._samples.append(np.asarray(position, dtype=float))

    def reset(self):
        self._samples = []

    @property
    def sample_count(self):
        return len(self._samples)

    def can_solidify(self):
        if len(self._samples) < self.MIN_SAMPLES_TO_SOLIDIFY:
            return False
        span = np.linalg.norm(self._samples[-1] - self._samples[0])
        return span >= self.MIN_SPAN_MM

    def fit_ray(self):
        """Least-squares best-fit 3D line through the collected samples
        (PCA: direction is the dominant principal component, origin is the
        sample centroid). Raises if not enough/degenerate data -- check
        can_solidify() first.
        """
        if not self.can_solidify():
            raise ValueError("not enough/degenerate samples to fit a ray")
        pts = np.array(self._samples)
        centroid = pts.mean(axis=0)
        centered = pts - centroid
        _, _, vh = np.linalg.svd(centered)
        direction = vh[0]
        # Orient direction to point from the walked-out (last) samples back
        # toward the screen (first samples) -- i.e. toward the corner --
        # so positive t from any point on the ray moves toward the corner.
        walk_direction = centered[0] - centered[-1]
        if np.dot(direction, walk_direction) < 0:
            direction = -direction
        direction = direction / np.linalg.norm(direction)
        return CalibrationRay(origin=centroid, direction=direction)


class ScreenCalibrator:
    """Orchestrates the full 4-corner calibration ritual and, once all 4
    are solidified, solves for the screen's corner points in Leap-space.
    """

    def __init__(
        self,
        known_width_mm,
        known_height_mm,
        mode=ScreenMode.MONITOR,
        on_corner_solidified=None,
        on_complete=None,
    ):
        """known_width_mm/known_height_mm: the screen's actual physical
        size, e.g. from its spec sheet or a tape measure. Required, not
        optional -- see module docstring for why the ray geometry alone
        can't disambiguate scale/position without it.
        """
        require_implemented(mode)
        self.mode = mode
        self.known_width_mm = known_width_mm
        self.known_height_mm = known_height_mm
        self.state = CalibrationState.WAITING_TO_POINT
        self.corner_index = 0
        self._collector = CornerCollector()
        self.rays = {}
        self.result = None
        self.on_corner_solidified = on_corner_solidified
        self.on_complete = on_complete

    @property
    def current_corner(self):
        if self.corner_index >= len(CORNER_ORDER):
            return None
        return CORNER_ORDER[self.corner_index]

    @property
    def is_complete(self):
        return self.state == CalibrationState.DONE

    def update(self, is_pointing, fingertip_position, is_fist):
        """Call once per tracking frame for the calibrating hand.

        Note the fist-to-solidify check happens *before* the pointing
        check: a real fist is definitionally not an extended-index
        pointing pose, so is_pointing will already be False by the time
        is_fist is True -- checking fist first is what lets a held pointing
        gesture transition straight into a fist without an in-between
        "pointing pose lost, trajectory discarded" frame eating the data
        the user just walked out to collect.
        """
        if self.is_complete:
            return

        if is_fist and self._collector.can_solidify():
            ray = self._collector.fit_ray()
            corner = self.current_corner
            self.rays[corner] = ray
            self._collector.reset()
            self.state = CalibrationState.WAITING_TO_POINT
            if self.on_corner_solidified:
                self.on_corner_solidified(corner, ray)
            self.corner_index += 1
            if self.corner_index >= len(CORNER_ORDER):
                self.state = CalibrationState.DONE
                self.result = solve_screen_plane(
                    self.rays, known_width_mm=self.known_width_mm,
                    known_height_mm=self.known_height_mm, mode=self.mode,
                )
                if self.on_complete:
                    self.on_complete(self.result)
            return

        if is_pointing:
            self.state = CalibrationState.COLLECTING
            self._collector.add_sample(fingertip_position)
        elif self.state == CalibrationState.COLLECTING:
            # Pointing pose released before a fist solidified it -- per the
            # ritual, only sample while actively pointing; drop the
            # in-progress trajectory rather than keep a broken one.
            self._collector.reset()
            self.state = CalibrationState.WAITING_TO_POINT


class ScreenCalibration:
    """Result of a completed calibration: the 4 corners in Leap-space, in
    CORNER_ORDER, plus the fitted plane normal.
    """

    def __init__(self, mode, corners, normal):
        self.mode = mode
        self.corners = corners  # dict: corner name -> np.array([x, y, z])
        self.normal = normal

    def corner_array(self):
        """Corners as an (4, 3) array, in CORNER_ORDER."""
        return np.array([self.corners[c] for c in CORNER_ORDER])

    def to_screen_uv(self, point):
        """Project a Leap-space 3D point onto the calibrated screen plane
        and express it as normalized (u, v) screen coordinates: (0, 0) =
        top_left, (1, 0) = top_right, (0, 1) = bottom_left, (1, 1) =
        bottom_right. Does not clamp to [0, 1] -- a point can project
        outside the screen's actual edges.
        """
        tl = self.corners["top_left"]
        tr = self.corners["top_right"]
        bl = self.corners["bottom_left"]
        u_axis = tr - tl
        v_axis = bl - tl
        u_len2 = np.dot(u_axis, u_axis)
        v_len2 = np.dot(v_axis, v_axis)
        rel = np.asarray(point, dtype=float) - tl
        u = np.dot(rel, u_axis) / u_len2
        v = np.dot(rel, v_axis) / v_len2
        return float(u), float(v)


def solve_screen_plane(rays, known_width_mm, known_height_mm, corner_order=CORNER_ORDER, mode=None):
    """Given 4 CalibrationRay objects (dict keyed by corner name) and the
    screen's actual known width/height in mm, solve for the 4 corner
    points C_i = origin_i + t_i * direction_i that best satisfy: each
    corner is a right angle, top/bottom width and left/right height match
    the known physical dimensions, and all 4 points are coplanar.

    Each ray alone only fixes a line, not a point -- t_i is unknown per
    ray. The rectangle/planarity/known-size constraints across all 4 rays
    together are what pin down the otherwise-ambiguous distance along each
    ray. known_width_mm/known_height_mm are required, not optional -- see
    module docstring for the empirically-confirmed reason ray geometry
    alone (right angles + equal sides + coplanar, with no absolute scale)
    is NOT sufficient to uniquely determine the rectangle. Solved
    numerically (scipy least_squares); see module docstring for
    validation status.
    """
    missing = [c for c in corner_order if c not in rays]
    if missing:
        raise ValueError(f"missing rays for corners: {missing}")
    if known_width_mm <= 0 or known_height_mm <= 0:
        raise ValueError("known_width_mm and known_height_mm must be positive")

    origins = np.array([rays[c].origin for c in corner_order])
    directions = np.array([rays[c].direction for c in corner_order])

    # Initial guess: the classic closed-form "closest point to multiple
    # skew lines" solution (least-squares over all 4 rays simultaneously),
    # then project each ray's own origin onto that point to get a
    # per-ray t0. Much better-conditioned than any single fixed distance
    # guess, since it's derived from where these specific 4 rays actually
    # converge rather than assumed -- still an initial guess, not the
    # answer (the least_squares call below does the real solving), but a
    # good one materially changes whether the optimizer lands on the
    # correct rectangle vs. some other stationary point satisfying the
    # soft constraints.
    A = np.zeros((3, 3))
    b = np.zeros(3)
    for o, d in zip(origins, directions):
        proj = np.eye(3) - np.outer(d, d)
        A += proj
        b += proj @ o
    center_estimate = np.linalg.lstsq(A, b, rcond=None)[0]
    t0 = np.array(
        [np.dot(center_estimate - origins[i], directions[i]) for i in range(4)]
    )
    t0 = np.clip(t0, 10.0, None)  # keep strictly in front of each ray's origin

    def residuals(t):
        pts = origins + t[:, None] * directions
        tl, tr, br, bl = pts
        res = [
            np.dot(tr - tl, bl - tl),  # right angle at TL
            np.dot(tl - tr, br - tr),  # right angle at TR
            np.dot(tr - br, bl - br),  # right angle at BR
            np.dot(br - bl, tl - bl),  # right angle at BL
        ]
        normal_guess = np.cross(tr - tl, bl - tl)
        norm = np.linalg.norm(normal_guess)
        if norm > 1e-9:
            normal_guess = normal_guess / norm
        res.append(np.dot(br - tl, normal_guess))  # coplanarity of BR
        res.append(np.linalg.norm(tr - tl) - np.linalg.norm(br - bl))  # top == bottom width
        res.append(np.linalg.norm(bl - tl) - np.linalg.norm(br - tr))  # left == right height
        # Known-size constraints -- these are what actually pin down scale
        # and position; without them the constraints above are satisfied
        # by more than one rectangle (confirmed via testing, see module
        # docstring), not just the true one.
        res.append(np.linalg.norm(tr - tl) - known_width_mm)
        res.append(np.linalg.norm(br - tr) - known_height_mm)
        return np.array(res)

    # Bounded to strictly positive t: negative t would put the
    # "corner" behind the ray's origin, the wrong direction relative
    # to how fit_ray()/the ray construction orient direction (toward
    # the corner). Without this bound the optimizer can and does find
    # spurious rectangle-shaped solutions using the wrong side of one
    # or more rays -- confirmed by direct debugging against known
    # ground truth, not a hypothetical concern.
    solution = least_squares(residuals, t0, bounds=(1.0, np.inf))
    t = solution.x
    pts = origins + t[:, None] * directions
    corners = {c: pts[i] for i, c in enumerate(corner_order)}

    tl, tr, bl = corners["top_left"], corners["top_right"], corners["bottom_left"]
    normal = np.cross(tr - tl, bl - tl)
    normal = normal / np.linalg.norm(normal)

    return ScreenCalibration(mode=mode, corners=corners, normal=normal)
