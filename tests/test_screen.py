"""Tests for cross-platform screen geometry and graceful platform degradation.

Both behaviours here guard *silent* failures, which is why they are tested
rather than left to manual checking:

  - A wrong screen size does not raise. The cursor still moves, it just
    lands somewhere else. Before this, every non-Linux host fell through to
    a hardcoded 1920x1080.
  - A missing X11 tool raised FileNotFoundError on the tracking callback
    thread, which would take down frame delivery rather than fail one
    gesture.
"""

import subprocess
import sys

from intuimotion.actions import windows
from intuimotion.sinks import screen


class TestEnvOverride:
    def test_parses_wxh(self, monkeypatch):
        monkeypatch.setenv("INTUIMOTION_SCREEN", "3840x1080")
        assert screen.screen_size() == (3840, 1080)

    def test_accepts_comma_and_spaces(self, monkeypatch):
        monkeypatch.setenv("INTUIMOTION_SCREEN", "2560, 1440")
        assert screen.screen_size() == (2560, 1440)

    def test_override_wins_over_every_probe(self, monkeypatch):
        monkeypatch.setenv("INTUIMOTION_SCREEN", "800x600")
        monkeypatch.setattr(screen, "_x11_size", lambda: (1920, 1080))
        monkeypatch.setattr(screen, "_xrandr_size", lambda: (1920, 1080))
        assert screen.screen_size() == (800, 600)

    def test_garbage_override_is_ignored_not_fatal(self, monkeypatch):
        monkeypatch.setenv("INTUIMOTION_SCREEN", "not-a-size")
        monkeypatch.setattr(screen, "_x11_size", lambda: (1280, 720))
        assert screen.screen_size() == (1280, 720)


class TestPlatformDispatch:
    def test_linux_defers_to_the_x11_probes(self, monkeypatch):
        monkeypatch.delenv("INTUIMOTION_SCREEN", raising=False)
        monkeypatch.setattr(sys, "platform", "linux")
        # None means "no native query here" -- the Linux answer comes from
        # Xlib/xrandr, which callers may mock.
        assert screen.native_screen_size() is None

    def test_windows_uses_the_native_query(self, monkeypatch):
        monkeypatch.delenv("INTUIMOTION_SCREEN", raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(screen, "_windows_size", lambda: (3840, 2160))
        assert screen.native_screen_size() == (3840, 2160)

    def test_macos_uses_the_native_query(self, monkeypatch):
        monkeypatch.delenv("INTUIMOTION_SCREEN", raising=False)
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(screen, "_macos_size", lambda: (2560, 1600))
        assert screen.native_screen_size() == (2560, 1600)


class TestFallbackChain:
    def test_falls_back_to_the_default_when_everything_fails(self, monkeypatch):
        monkeypatch.delenv("INTUIMOTION_SCREEN", raising=False)
        monkeypatch.setattr(screen, "native_screen_size", lambda: None)
        monkeypatch.setattr(screen, "_x11_size", lambda: None)
        monkeypatch.setattr(screen, "_xrandr_size", lambda: None)
        assert screen.screen_size() == screen.DEFAULT_SIZE

    def test_a_probe_that_raises_does_not_propagate(self, monkeypatch):
        monkeypatch.delenv("INTUIMOTION_SCREEN", raising=False)
        monkeypatch.setattr(screen, "_x11_size", lambda: None)
        monkeypatch.setattr(screen, "_xrandr_size", lambda: (1600, 900))
        assert screen.screen_size() == (1600, 900)


class TestMouseUsesNativeSizeFirst:
    def test_native_size_short_circuits_xrandr(self, monkeypatch):
        from intuimotion.actions import mouse

        monkeypatch.setattr(mouse, "native_screen_size", lambda: (3000, 2000))

        def explode(*args, **kwargs):
            raise AssertionError("xrandr must not run when a native size exists")

        monkeypatch.setattr(mouse.subprocess, "run", explode)
        assert mouse._detect_screen_size() == (3000, 2000)


class TestWindowToolsDegradeGracefully:
    def test_missing_tool_does_not_raise(self, monkeypatch):
        # This runs on the tracking callback thread; a raise here would stop
        # frame delivery, not just fail one gesture.
        def missing(*args, **kwargs):
            raise FileNotFoundError("xprop")

        monkeypatch.setattr(windows.subprocess, "run", missing)
        windows._missing_tool_warned.clear()
        assert windows._list_window_ids() == []

    def test_minimize_all_is_a_no_op_without_the_tools(self, monkeypatch):
        def missing(*args, **kwargs):
            raise FileNotFoundError("xprop")

        monkeypatch.setattr(windows.subprocess, "run", missing)
        windows._missing_tool_warned.clear()
        windows.minimize_all_except_terminal()  # must not raise

    def test_warns_once_per_tool_not_once_per_call(self, monkeypatch, capsys):
        def missing(*args, **kwargs):
            raise FileNotFoundError("xprop")

        monkeypatch.setattr(windows.subprocess, "run", missing)
        windows._missing_tool_warned.clear()
        for _ in range(5):
            windows._run(["xprop", "-root"])
        assert capsys.readouterr().out.count("unavailable") == 1

    def test_timeout_is_also_survived(self, monkeypatch):
        def slow(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="xprop", timeout=3)

        monkeypatch.setattr(windows.subprocess, "run", slow)
        windows._missing_tool_warned.clear()
        assert windows._run(["xprop", "-root"]).returncode == 1
