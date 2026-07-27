import numpy as np
import pytest

from intuimotion.boundary_calibration import EdgeTracer, BoundaryCalibrator
from intuimotion.screen_modes import ScreenMode, ScreenModeNotImplementedError


# ---------------------------------------------------------------------------
# EdgeTracer
# ---------------------------------------------------------------------------

def test_starts_in_waiting_for_start_lock():
    t = EdgeTracer()
    assert t.state == EdgeTracer.WAITING_FOR_START_LOCK
    assert not t.is_done


def test_losing_pointing_pose_before_lock_does_not_crash_and_stays_waiting():
    t = EdgeTracer()
    t.update(is_pointing=True, position=(0, 0, 0), now=0.0)
    t.update(is_pointing=False, position=(0, 0, 0), now=0.1)
    assert t.state == EdgeTracer.WAITING_FOR_START_LOCK
    assert t.start_point is None


def test_holding_still_while_pointing_locks_start_after_dwell():
    t = EdgeTracer()
    # hold at the same position for longer than HOLD_DWELL
    now = 0.0
    step = 0.05
    while now < EdgeTracer.HOLD_DWELL + 0.1:
        t.update(is_pointing=True, position=(100, 200, 300), now=now)
        now += step
    assert t.state == EdgeTracer.TRACING
    assert np.allclose(t.start_point, [100, 200, 300])


def test_brief_pause_right_after_start_lock_does_not_immediately_end_trace():
    """Regression guard for the exact bug MIN_TRACE_SPAN_MM exists to
    prevent: right after locking the start point, the hand is by
    definition still (same position) -- without a minimum-travel guard,
    that stillness would immediately satisfy the end-lock condition too.
    """
    t = EdgeTracer()
    now = 0.0
    step = 0.05
    while now < EdgeTracer.HOLD_DWELL + 0.1:
        t.update(is_pointing=True, position=(0, 0, 0), now=now)
        now += step
    assert t.state == EdgeTracer.TRACING

    # stay at (roughly) the same spot for another full dwell period --
    # should NOT end the trace, since MIN_TRACE_SPAN_MM hasn't been covered
    still_start = now
    while now < still_start + EdgeTracer.HOLD_DWELL + 0.1:
        t.update(is_pointing=True, position=(0, 0, 1), now=now)  # 1mm jitter
        now += step
    assert t.state == EdgeTracer.TRACING
    assert not t.is_done


def test_full_trace_start_move_hold_locks_end_point():
    t = EdgeTracer()
    now = 0.0
    step = 0.05

    # lock start at (0,0,0)
    while now < EdgeTracer.HOLD_DWELL + 0.1:
        t.update(is_pointing=True, position=(0, 0, 0), now=now)
        now += step

    # move down (z decreasing) fast enough to not be "still" mid-trace
    for i in range(20):
        now += step
        t.update(is_pointing=True, position=(0, 0, -i * 40), now=now)

    last_z = -19 * 40
    # hold still at the bottom
    hold_start = now
    while now < hold_start + EdgeTracer.HOLD_DWELL + 0.1:
        now += step
        t.update(is_pointing=True, position=(0, 0, last_z), now=now)

    assert t.is_done
    assert np.allclose(t.start_point, [0, 0, 0])
    assert np.allclose(t.end_point, [0, 0, last_z])
    assert len(t.trace_points) > 5


def test_fitted_line_recovers_a_noisy_straight_trace():
    t = EdgeTracer()
    rng = np.random.default_rng(42)
    now = 0.0
    step = 0.05

    while now < EdgeTracer.HOLD_DWELL + 0.1:
        t.update(is_pointing=True, position=(0, 0, 0), now=now)
        now += step

    for i in range(1, 20):
        now += step
        noise = rng.normal(scale=2.0, size=3)  # 2mm hand tremor
        pos = np.array([0, 0, -i * 40]) + noise
        t.update(is_pointing=True, position=pos, now=now)

    hold_start = now
    while now < hold_start + EdgeTracer.HOLD_DWELL + 0.1:
        now += step
        t.update(is_pointing=True, position=(0, 0, -19 * 40), now=now)

    assert t.is_done
    refined_start, refined_end = t.fitted_line()
    # the fitted line should recover the true (0,0,0) -> (0,0,-760) edge
    # more closely than raw noise alone would guarantee for a single point
    assert np.allclose(refined_start[:2], [0, 0], atol=2.0)
    assert np.allclose(refined_end[:2], [0, 0], atol=2.0)


# ---------------------------------------------------------------------------
# BoundaryCalibrator
# ---------------------------------------------------------------------------

def _run_edge(tracer, start, end, steps=20):
    now = [0.0]
    step = 0.05

    def hold(pos, duration):
        t0 = now[0]
        while now[0] < t0 + duration + 0.1:
            tracer.update(is_pointing=True, position=pos, now=now[0])
            now[0] += step

    hold(start, EdgeTracer.HOLD_DWELL)
    start = np.array(start, dtype=float)
    end = np.array(end, dtype=float)
    for i in range(1, steps):
        now[0] += step
        pos = start + (end - start) * (i / steps)
        tracer.update(is_pointing=True, position=pos, now=now[0])
    hold(tuple(end), EdgeTracer.HOLD_DWELL)


def test_boundary_calibrator_rejects_not_implemented_modes():
    with pytest.raises(ScreenModeNotImplementedError):
        BoundaryCalibrator(mode=ScreenMode.AR)


def test_boundary_calibrator_completes_once_both_hands_done():
    cal = BoundaryCalibrator(use_fitted_line=False)
    assert not cal.is_complete

    _run_edge(cal.left, start=(0, 0, 0), end=(0, 0, -600))
    assert not cal.is_complete  # only one hand done so far

    _run_edge(cal.right, start=(1000, 0, 0), end=(1000, 0, -600))
    assert cal.is_complete
    assert cal.result is not None


def test_boundary_calibrator_recovers_correct_corners():
    cal = BoundaryCalibrator(use_fitted_line=False)
    _run_edge(cal.left, start=(0, 0, 0), end=(0, 0, -600))
    _run_edge(cal.right, start=(1000, 0, 0), end=(1000, 0, -600))

    assert np.allclose(cal.result.corners["top_left"], [0, 0, 0])
    assert np.allclose(cal.result.corners["top_right"], [1000, 0, 0])
    assert np.allclose(cal.result.corners["bottom_left"], [0, 0, -600])
    assert np.allclose(cal.result.corners["bottom_right"], [1000, 0, -600])


def test_boundary_calibrator_to_screen_uv():
    cal = BoundaryCalibrator(use_fitted_line=False)
    _run_edge(cal.left, start=(0, 0, 0), end=(0, 0, -600))
    _run_edge(cal.right, start=(1000, 0, 0), end=(1000, 0, -600))

    u, v = cal.result.to_screen_uv([500, 0, -300])  # dead center
    assert np.allclose([u, v], [0.5, 0.5], atol=1e-6)

    u, v = cal.result.to_screen_uv([0, 0, 0])
    assert np.allclose([u, v], [0.0, 0.0], atol=1e-6)
