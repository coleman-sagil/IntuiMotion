import numpy as np
import pytest

from intuimotion.calibration import (
    CornerCollector,
    CalibrationRay,
    ScreenCalibrator,
    CalibrationState,
    CORNER_ORDER,
    solve_screen_plane,
)
from intuimotion.screen_modes import ScreenMode, ScreenModeNotImplementedError


# ---------------------------------------------------------------------------
# CornerCollector / ray fitting
# ---------------------------------------------------------------------------

def test_cannot_solidify_with_too_few_samples():
    c = CornerCollector()
    for i in range(3):
        c.add_sample((0, 0, i * 100))
    assert not c.can_solidify()


def test_cannot_solidify_with_degenerate_span():
    c = CornerCollector()
    for _ in range(10):
        c.add_sample((0, 0, 0))  # no movement at all
    assert not c.can_solidify()


def test_can_solidify_with_enough_spread_samples():
    c = CornerCollector()
    for i in range(10):
        c.add_sample((0, 0, i * 20))  # spans 180mm along z
    assert c.can_solidify()


def test_fit_ray_recovers_a_known_straight_line():
    # Walk from (0,0,0) out to (0,0,400) along z -- a perfectly straight,
    # noise-free trajectory. Direction should point back toward the start
    # (the "corner" side) once fit.
    c = CornerCollector()
    for i in range(9):
        c.add_sample((0, 0, i * 50))
    ray = c.fit_ray()
    # direction should be +/- z; after orientation, it points from the
    # last sample back toward the first (i.e. -z, toward (0,0,0))
    assert np.allclose(np.abs(ray.direction), [0, 0, 1], atol=1e-6)
    assert ray.direction[2] < 0
    # centroid of 0..400 in steps of 50 (9 points: 0,50,...,400) is 200
    assert np.allclose(ray.origin, [0, 0, 200], atol=1e-6)


def test_fit_ray_raises_if_not_solidifiable():
    c = CornerCollector()
    with pytest.raises(ValueError):
        c.fit_ray()


# ---------------------------------------------------------------------------
# ScreenCalibrator state machine
# ---------------------------------------------------------------------------

def _walk_out_and_solidify(calibrator, start, direction, steps=10, step_mm=40):
    """Simulate one corner: point, walk out along `direction` from `start`
    for `steps` samples, then close a fist to solidify."""
    for i in range(steps):
        pos = tuple(np.array(start) + np.array(direction) * (i * step_mm))
        calibrator.update(is_pointing=True, fingertip_position=pos, is_fist=False)
    calibrator.update(is_pointing=False, fingertip_position=(0, 0, 0), is_fist=True)


def test_calibrator_rejects_not_implemented_modes():
    with pytest.raises(ScreenModeNotImplementedError):
        ScreenCalibrator(1000, 600, mode=ScreenMode.AR)
    with pytest.raises(ScreenModeNotImplementedError):
        ScreenCalibrator(1000, 600, mode=ScreenMode.CAR)


def test_calibrator_accepts_monitor_and_tv():
    ScreenCalibrator(1000, 600, mode=ScreenMode.MONITOR)
    ScreenCalibrator(1000, 600, mode=ScreenMode.TV)


def test_pointing_pose_lost_before_fist_discards_trajectory():
    cal = ScreenCalibrator(1000, 600)
    for i in range(9):
        cal.update(is_pointing=True, fingertip_position=(0, 0, i * 50), is_fist=False)
    assert cal.state == CalibrationState.COLLECTING
    # hand relaxes out of pointing pose without a fist -- trajectory should drop
    cal.update(is_pointing=False, fingertip_position=(0, 0, 999), is_fist=False)
    assert cal.state == CalibrationState.WAITING_TO_POINT
    assert cal._collector.sample_count == 0


def test_fist_too_early_does_not_solidify():
    cal = ScreenCalibrator(1000, 600)
    for i in range(3):  # below MIN_SAMPLES_TO_SOLIDIFY
        cal.update(is_pointing=True, fingertip_position=(0, 0, i * 50), is_fist=False)
    cal.update(is_pointing=False, fingertip_position=(0, 0, 0), is_fist=True)
    assert cal.corner_index == 0
    assert cal.rays == {}


def test_full_ritual_advances_through_all_four_corners_in_order():
    cal = ScreenCalibrator(1000, 600)
    seen_corners = []
    cal.on_corner_solidified = lambda corner, ray: seen_corners.append(corner)

    directions = {
        "top_left": (1, 0, 0),
        "top_right": (0, 1, 0),
        "bottom_right": (0, 0, 1),
        "bottom_left": (1, 1, 0),
    }
    for i, corner in enumerate(CORNER_ORDER):
        assert cal.current_corner == corner
        _walk_out_and_solidify(cal, start=(i * 500, 0, 0), direction=directions[corner])

    assert seen_corners == list(CORNER_ORDER)
    assert cal.is_complete
    assert cal.result is not None
    assert set(cal.result.corners.keys()) == set(CORNER_ORDER)


def test_calibration_does_not_process_further_updates_once_complete():
    cal = ScreenCalibrator(1000, 600)
    directions = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1)]
    for i, corner in enumerate(CORNER_ORDER):
        _walk_out_and_solidify(cal, start=(i * 500, 0, 0), direction=directions[i])
    assert cal.is_complete
    result_before = cal.result
    cal.update(is_pointing=True, fingertip_position=(1, 2, 3), is_fist=False)
    assert cal.result is result_before  # unchanged


# ---------------------------------------------------------------------------
# solve_screen_plane -- validated against known synthetic ground truth
# ---------------------------------------------------------------------------

def _rays_toward_known_rectangle(corners, ray_origin_offset=(0, -500, 200)):
    """Build exact CalibrationRay objects that point precisely at each
    known corner, from an arbitrary origin per corner (simulating "the
    user's hand ended up somewhere, but was aimed exactly at the corner").
    """
    rays = {}
    offset = np.array(ray_origin_offset, dtype=float)
    for i, name in enumerate(CORNER_ORDER):
        corner = np.array(corners[name], dtype=float)
        origin = corner + offset + np.array([i * 37.0, i * -19.0, i * 11.0])
        direction = corner - origin
        direction = direction / np.linalg.norm(direction)
        rays[name] = CalibrationRay(origin=origin, direction=direction)
    return rays


def test_solve_screen_plane_recovers_an_axis_aligned_rectangle():
    ground_truth = {
        "top_left": (0, 0, 0),
        "top_right": (1000, 0, 0),
        "bottom_right": (1000, -600, 0),
        "bottom_left": (0, -600, 0),
    }
    rays = _rays_toward_known_rectangle(ground_truth)
    result = solve_screen_plane(rays, known_width_mm=1000, known_height_mm=600)
    for name, expected in ground_truth.items():
        assert np.allclose(result.corners[name], expected, atol=1.0), name


def test_solve_screen_plane_recovers_a_tilted_rectangle():
    # A rectangle rotated off-axis and offset in 3D, not conveniently
    # aligned to any coordinate plane -- exercises the general case, not
    # just the easy axis-aligned one above.
    theta = 0.4
    rot = np.array(
        [
            [np.cos(theta), 0, np.sin(theta)],
            [0, 1, 0],
            [-np.sin(theta), 0, np.cos(theta)],
        ]
    )
    local = {
        "top_left": np.array([0, 0, 0]),
        "top_right": np.array([800, 0, 0]),
        "bottom_right": np.array([800, -450, 0]),
        "bottom_left": np.array([0, -450, 0]),
    }
    offset = np.array([150.0, 250.0, -80.0])
    ground_truth = {name: (rot @ pt) + offset for name, pt in local.items()}

    rays = _rays_toward_known_rectangle(ground_truth)
    result = solve_screen_plane(rays, known_width_mm=800, known_height_mm=450)
    for name, expected in ground_truth.items():
        assert np.allclose(result.corners[name], expected, atol=1.0), name


def test_solve_screen_plane_raises_on_missing_corner():
    with pytest.raises(ValueError):
        solve_screen_plane(
            {"top_left": CalibrationRay((0, 0, 0), (0, 0, 1))},
            known_width_mm=1000, known_height_mm=600,
        )


def test_solve_screen_plane_rejects_nonpositive_dimensions():
    ground_truth = {
        "top_left": (0, 0, 0), "top_right": (1000, 0, 0),
        "bottom_right": (1000, -600, 0), "bottom_left": (0, -600, 0),
    }
    rays = _rays_toward_known_rectangle(ground_truth)
    with pytest.raises(ValueError):
        solve_screen_plane(rays, known_width_mm=0, known_height_mm=600)
    with pytest.raises(ValueError):
        solve_screen_plane(rays, known_width_mm=1000, known_height_mm=-1)


def test_to_screen_uv_maps_corners_to_unit_square():
    ground_truth = {
        "top_left": (0, 0, 0),
        "top_right": (1000, 0, 0),
        "bottom_right": (1000, -600, 0),
        "bottom_left": (0, -600, 0),
    }
    rays = _rays_toward_known_rectangle(ground_truth)
    result = solve_screen_plane(rays, known_width_mm=1000, known_height_mm=600)

    u, v = result.to_screen_uv(result.corners["top_left"])
    assert np.allclose([u, v], [0, 0], atol=1e-6)
    u, v = result.to_screen_uv(result.corners["top_right"])
    assert np.allclose([u, v], [1, 0], atol=1e-6)
    u, v = result.to_screen_uv(result.corners["bottom_left"])
    assert np.allclose([u, v], [0, 1], atol=1e-6)
    u, v = result.to_screen_uv(result.corners["bottom_right"])
    assert np.allclose([u, v], [1, 1], atol=1e-6)

    # a point in the middle of the screen should map to (0.5, 0.5)
    mid = np.mean([ground_truth[c] for c in CORNER_ORDER], axis=0)
    u, v = result.to_screen_uv(mid)
    assert np.allclose([u, v], [0.5, 0.5], atol=1e-6)
