"""Tests for the mockable, hand-routing surface of mpx_mouse.

MpxPointer itself (real xinput subprocess calls, real X connections) is
deliberately not exercised here -- same reasoning as mouse.py's pynput
Controller never being driven for real in tests: touching the real X
server's master-pointer set from an automated test run is a real side
effect (device creation, headless-CI failure, debris on a crashed run),
not a unit of logic. What's tested is the part that is logic: routing a
hand_type to the right pointer object, and dry-run gating -- both via
fake pointer objects swapped into the module-level registry, the same
monkeypatch.setitem/setattr pattern the rest of this suite already uses.
"""
import pytest

from intuimotion.actions import dry_run, mpx_mouse


@pytest.fixture(autouse=True)
def _reset_dry_run():
    dry_run.set_enabled(False)
    yield
    dry_run.set_enabled(False)


class _FakePointer:
    def __init__(self):
        self.moved_to = []
        self.pressed = []
        self.released = []

    def move_to(self, x, y):
        self.moved_to.append((x, y))

    def press(self, button):
        self.pressed.append(button)

    def release(self, button):
        self.released.append(button)


@pytest.fixture
def fake_pointers(monkeypatch):
    left, right = _FakePointer(), _FakePointer()
    monkeypatch.setitem(mpx_mouse._pointers, "Left", left)
    monkeypatch.setitem(mpx_mouse._pointers, "Right", right)
    return {"Left": left, "Right": right}


class _FakeHandType:
    """Stands in for LeapC's HandType enum member, which exposes .name but
    is not itself a string."""

    def __init__(self, name):
        self.name = name


def test_hand_key_normalizes_string_and_enum_like_hand_types():
    assert mpx_mouse._hand_key("Left") == "Left"
    assert mpx_mouse._hand_key(_FakeHandType("Right")) == "Right"


def test_move_to_routes_to_the_hand_specific_pointer_only(fake_pointers):
    mpx_mouse.move_to("Left", 12, 34)

    assert fake_pointers["Left"].moved_to == [(12, 34)]
    assert fake_pointers["Right"].moved_to == []


def test_move_to_accepts_enum_like_hand_type(fake_pointers):
    mpx_mouse.move_to(_FakeHandType("Right"), 1, 2)

    assert fake_pointers["Right"].moved_to == [(1, 2)]
    assert fake_pointers["Left"].moved_to == []


def test_move_to_leap_position_maps_before_routing(monkeypatch, fake_pointers):
    monkeypatch.setattr(mpx_mouse, "map_to_screen", lambda x, y: (x * 2, y * 3))

    mpx_mouse.move_to_leap_position("Left", 10, 20)

    assert fake_pointers["Left"].moved_to == [(20, 60)]
    assert fake_pointers["Right"].moved_to == []


def test_press_and_release_route_independently_per_hand(fake_pointers):
    mpx_mouse.press("Right", "left")
    mpx_mouse.press("Left", "right")
    mpx_mouse.release("Right", "left")

    assert fake_pointers["Right"].pressed == ["left"]
    assert fake_pointers["Left"].pressed == ["right"]
    assert fake_pointers["Right"].released == ["left"]
    assert fake_pointers["Left"].released == []


def test_press_defaults_to_left_button(fake_pointers):
    mpx_mouse.press("Left")

    assert fake_pointers["Left"].pressed == ["left"]


def test_button_numbers_map_right_to_3_and_everything_else_to_1():
    # MpxPointer.press/release feed this straight to XTestFakeButtonEvent's
    # `detail` -- button 1 is left, button 3 is right on a standard X button
    # mapping (mirrors mouse.py's Button.right/Button.left convention).
    assert mpx_mouse._BUTTON_NUMBERS.get("right", 1) == 3
    assert mpx_mouse._BUTTON_NUMBERS.get("left", 1) == 1
    assert mpx_mouse._BUTTON_NUMBERS.get("anything-else", 1) == 1


def test_dry_run_skips_the_real_pointer_for_move_press_release(fake_pointers):
    dry_run.set_enabled(True)

    mpx_mouse.move_to("Left", 1, 2)
    mpx_mouse.press("Left", "left")
    mpx_mouse.release("Left", "left")

    assert fake_pointers["Left"].moved_to == []
    assert fake_pointers["Left"].pressed == []
    assert fake_pointers["Left"].released == []
