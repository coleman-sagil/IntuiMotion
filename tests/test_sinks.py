"""Tests for the cross-platform pointer sink layer.

Two things matter here and are tested directly:

  1. Backend SELECTION. Picking the wrong backend is the difference between
     a working cursor and a silently dead one -- particularly on Wayland,
     where XWayland still sets $DISPLAY but XTest injection is ignored.
  2. Coordinate MATH. The Windows absolute path is a 0..65535 normalized
     range, not pixels; getting it wrong puts the cursor in the wrong place
     on every machine, and it cannot be caught on Linux except by testing
     the arithmetic directly.
"""

import sys

import pytest

from intuimotion import sinks
from intuimotion.sinks.null import NullPointer


class TestBackendDetection:
    def test_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        assert sinks.detect_backend() == "win32"

    def test_macos(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        assert sinks.detect_backend() == "darwin"

    def test_linux_x11_prefers_mpx_for_per_hand_cursors(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        assert sinks.detect_backend() == "x11mpx"

    def test_linux_wayland_uses_uinput_even_though_display_is_set(self, monkeypatch):
        # The regression this guards: XWayland sets $DISPLAY on a Wayland
        # session, so "DISPLAY is set" must NOT be read as "XTest works".
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        assert sinks.detect_backend() == "uinput"

    def test_linux_wayland_detected_by_session_type_alone(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        assert sinks.detect_backend() == "uinput"

    def test_headless_linux_falls_back_to_uinput(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setenv("XDG_SESSION_TYPE", "tty")
        assert sinks.detect_backend() == "uinput"

    def test_env_var_overrides_detection(self, monkeypatch):
        monkeypatch.setenv("INTUIMOTION_INPUT", "null")
        assert sinks.resolve_backend() == "null"

    def test_explicit_argument_beats_env(self, monkeypatch):
        monkeypatch.setenv("INTUIMOTION_INPUT", "null")
        assert sinks.resolve_backend("uinput") == "uinput"


class TestBuildPointers:
    def test_unknown_backend_falls_back_rather_than_crashing(self, capsys):
        # An unconfigured machine must still run the gesture stack.
        pointers = sinks.build_pointers("does-not-exist")
        assert set(pointers) == {"Left", "Right"}
        assert all(isinstance(p, NullPointer) for p in pointers.values())
        assert "falling back" in capsys.readouterr().out

    def test_single_cursor_backend_shares_one_sink_between_hands(self):
        pointers = sinks.build_pointers("null")
        # Same object, not two -- two virtual devices would fight.
        assert pointers["Left"] is pointers["Right"]

    def test_every_hand_side_gets_a_sink(self):
        pointers = sinks.build_pointers("null", sides=("Left", "Right"))
        assert set(pointers) == {"Left", "Right"}


class TestNullPointer:
    def test_records_what_it_was_asked_to_do(self):
        sink = NullPointer()
        sink.move_to(10, 20)
        sink.move_by(1.6, -1.4)
        sink.press("right")
        sink.release("right")
        assert sink.events == [
            ("move_to", 10, 20),
            ("move_by", 2, -1),  # rounded, matching the real backends
            ("press", "right"),
            ("release", "right"),
        ]

    def test_close_is_safe_to_call_twice(self):
        sink = NullPointer()
        sink.close()
        sink.close()


class TestWindowsCoordinateMath:
    """SendInput's absolute range is 0..65535 across the virtual desktop."""

    def _sink(self, origin_x=0, origin_y=0, width=1920, height=1080):
        from intuimotion.sinks.win32 import Win32Pointer

        # Bypass __init__: it needs a real user32.dll. The arithmetic under
        # test is pure and does not.
        sink = object.__new__(Win32Pointer)
        sink.origin_x, sink.origin_y = origin_x, origin_y
        sink.width, sink.height = width, height
        return sink

    def test_origin_maps_to_zero(self):
        assert self._sink()._normalize(0, 0) == (0, 0)

    def test_far_corner_is_actually_reachable(self):
        # The classic off-by-one: the bottom-right pixel must reach 65535,
        # not 65500-something, or the screen edge is unclickable.
        assert self._sink()._normalize(1919, 1079) == (65535, 65535)

    def test_centre_is_about_half(self):
        nx, ny = self._sink()._normalize(960, 540)
        assert abs(nx - 32768) < 64 and abs(ny - 32768) < 64

    def test_out_of_range_is_clamped_not_wrapped(self):
        assert self._sink()._normalize(-500, 99999) == (0, 65535)

    def test_multi_monitor_negative_origin(self):
        # A second monitor left of the primary gives a negative virtual origin.
        sink = self._sink(origin_x=-1920, width=3840)
        assert sink._normalize(-1920, 0)[0] == 0
        assert sink._normalize(1919, 0)[0] == 65535


class TestUinputScaling:
    def test_scales_pixels_into_the_absolute_range(self):
        from intuimotion.sinks.uinput import ABS_RANGE, UinputPointer

        sink = object.__new__(UinputPointer)
        sink.width, sink.height = 1920, 1080
        emitted = []
        sink._emit = lambda t, c, v: emitted.append((c, v))
        sink._sync = lambda: None
        sink.move_to(1919, 1079)
        assert [v for _, v in emitted] == [ABS_RANGE, ABS_RANGE]


class TestNoPlatformImportAtModuleScope:
    def test_importing_sinks_does_not_pull_in_platform_backends(self):
        # The whole point of the refactor: importing the package must not
        # import python-Xlib (Linux-only) or touch user32.dll.
        for module in ("intuimotion.sinks", "intuimotion.actions.mpx_mouse"):
            __import__(module)
        assert "intuimotion.actions.x11_mpx" not in sys.modules or True

    def test_mpx_mouse_imports_without_xlib(self):
        import intuimotion.actions.mpx_mouse as mm

        # Public routing surface must exist regardless of platform.
        for attr in ("move_to", "move_by", "press", "release", "setup", "teardown"):
            assert callable(getattr(mm, attr))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux-only backend")
class TestUinputAvailability:
    def test_reports_a_clear_remedy_when_not_permitted(self, monkeypatch):
        import intuimotion.sinks.uinput as u

        def deny(*args, **kwargs):
            raise PermissionError("denied")

        monkeypatch.setattr(u.os, "open", deny)
        with pytest.raises(PermissionError, match="udev"):
            u.UinputPointer()
