import subprocess

from intuimotion.actions import mouse


def test_map_to_screen_maps_leap_box_corners_to_screen_corners(monkeypatch):
    monkeypatch.setattr(mouse, "SCREEN_WIDTH", 3840)
    monkeypatch.setattr(mouse, "SCREEN_HEIGHT", 1080)
    monkeypatch.setattr(mouse, "LEAP_X_RANGE", (-150.0, 150.0))
    monkeypatch.setattr(mouse, "LEAP_Y_RANGE", (100.0, 400.0))

    assert mouse.map_to_screen(-150.0, 100.0) == (0.0, 1080.0)
    assert mouse.map_to_screen(150.0, 400.0) == (3840.0, 0.0)


def test_map_to_screen_flips_y_axis(monkeypatch):
    monkeypatch.setattr(mouse, "SCREEN_WIDTH", 1000)
    monkeypatch.setattr(mouse, "SCREEN_HEIGHT", 1000)
    monkeypatch.setattr(mouse, "LEAP_X_RANGE", (0.0, 100.0))
    monkeypatch.setattr(mouse, "LEAP_Y_RANGE", (0.0, 100.0))

    # A higher Leap y (hand higher up) should map to a *lower* screen y
    # (closer to the top of the screen), since screen coordinates grow
    # downward while Leap's grow upward.
    _, low_screen_y = mouse.map_to_screen(50.0, 100.0)
    _, high_screen_y = mouse.map_to_screen(50.0, 0.0)

    assert low_screen_y < high_screen_y


def test_map_to_screen_clamps_out_of_range_leap_coordinates(monkeypatch):
    monkeypatch.setattr(mouse, "SCREEN_WIDTH", 1000)
    monkeypatch.setattr(mouse, "SCREEN_HEIGHT", 1000)
    monkeypatch.setattr(mouse, "LEAP_X_RANGE", (0.0, 100.0))
    monkeypatch.setattr(mouse, "LEAP_Y_RANGE", (0.0, 100.0))

    screen_x, screen_y = mouse.map_to_screen(-9999.0, 9999.0)

    assert (screen_x, screen_y) == (0.0, 0.0)


class _FakeMouseController:
    """Stands in for pynput's Controller so the relative-move tests can run
    without moving the real cursor -- the same reason mouse.subprocess is
    faked below rather than really shelling out to xrandr."""

    def __init__(self):
        self.moved_by = []

    def move(self, dx, dy):
        self.moved_by.append((dx, dy))


def test_move_by_passes_integer_offsets_to_the_relative_move(monkeypatch):
    fake = _FakeMouseController()
    monkeypatch.setattr(mouse, "_mouse", fake)

    mouse.move_by(3.6, -2.4)

    # Rounded, not truncated -- and .move() (relative), not .position.
    assert fake.moved_by == [(4, -2)]


def test_move_by_leap_delta_scales_millimeters_by_sensitivity(monkeypatch):
    fake = _FakeMouseController()
    monkeypatch.setattr(mouse, "_mouse", fake)
    monkeypatch.setattr(mouse, "MOUSE_SENSITIVITY", 5.0)

    mouse.move_by_leap_delta(2.0, 0.0)

    assert fake.moved_by == [(10, 0)]


def test_move_by_leap_delta_moves_cursor_up_when_hand_pushes_away(monkeypatch):
    fake = _FakeMouseController()
    monkeypatch.setattr(mouse, "_mouse", fake)
    monkeypatch.setattr(mouse, "MOUSE_SENSITIVITY", 1.0)

    # Leap's +z increases toward the user, so pushing the hand away from the
    # user is a *negative* dz, and that should move the cursor up the screen
    # (a negative screen dy, since screen y grows downward) -- push away =
    # up, like a physical touchpad. Untuned sign, see move_by_leap_delta.
    mouse.move_by_leap_delta(0.0, -3.0)
    (_, push_away_dy), = fake.moved_by

    assert push_away_dy < 0


def test_move_by_leap_delta_of_zero_does_not_move_the_cursor(monkeypatch):
    # GestureInterpreter emits (0.0, 0.0) on the first in-band frame after
    # engaging or re-entering the clutch band -- it must not jump the cursor.
    fake = _FakeMouseController()
    monkeypatch.setattr(mouse, "_mouse", fake)

    mouse.move_by_leap_delta(0.0, 0.0)

    assert fake.moved_by == [(0, 0)]


class _FakeCompletedProcess:
    def __init__(self, stdout):
        self.stdout = stdout


def test_detect_screen_size_parses_xrandr_current_resolution(monkeypatch):
    fake_output = (
        "Screen 0: minimum 8 x 8, current 3840 x 1080, maximum 32767 x 32767\n"
        "DP-2 connected 1920x1080+0+0 ...\n"
    )
    monkeypatch.setattr(
        mouse.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(fake_output)
    )

    assert mouse._detect_screen_size() == (3840, 1080)


def test_detect_screen_size_falls_back_when_xrandr_missing(monkeypatch):
    def raise_not_found(*args, **kwargs):
        raise FileNotFoundError("xrandr not found")

    monkeypatch.setattr(mouse.subprocess, "run", raise_not_found)

    assert mouse._detect_screen_size() == (1920, 1080)


def test_detect_screen_size_falls_back_on_timeout(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="xrandr", timeout=2)

    monkeypatch.setattr(mouse.subprocess, "run", raise_timeout)

    assert mouse._detect_screen_size() == (1920, 1080)


def test_detect_screen_size_falls_back_on_unparseable_output(monkeypatch):
    monkeypatch.setattr(
        mouse.subprocess, "run", lambda *a, **k: _FakeCompletedProcess("not xrandr output")
    )

    assert mouse._detect_screen_size() == (1920, 1080)
