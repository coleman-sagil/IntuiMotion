import pytest

from intuimotion.actions import dry_run, macros, media, mouse, windows


@pytest.fixture(autouse=True)
def _reset_dry_run():
    dry_run.set_enabled(False)
    yield
    dry_run.set_enabled(False)


def test_guarded_calls_real_function_when_disabled():
    calls = []

    @dry_run.guarded(lambda x: f"describe {x}")
    def real(x):
        calls.append(x)
        return "real result"

    result = real(5)

    assert calls == [5]
    assert result == "real result"


def test_guarded_skips_real_function_when_enabled(capsys):
    calls = []
    dry_run.set_enabled(True)

    @dry_run.guarded(lambda x: f"describe {x}")
    def real(x):
        calls.append(x)
        return "real result"

    result = real(5)

    assert calls == []
    assert result is None
    assert "[dry-run] describe 5" in capsys.readouterr().out


def test_mouse_click_does_not_call_pynput_when_dry_run(monkeypatch):
    dry_run.set_enabled(True)
    calls = []
    monkeypatch.setattr(mouse._mouse, "click", lambda button: calls.append(button))

    mouse.click("left")

    assert calls == []


def test_media_play_pause_does_not_call_pynput_when_dry_run(monkeypatch):
    dry_run.set_enabled(True)
    calls = []
    monkeypatch.setattr(media._keyboard, "tap", lambda key: calls.append(key))

    media.play_pause()

    assert calls == []


def test_macros_run_shell_does_not_spawn_process_when_dry_run(monkeypatch):
    dry_run.set_enabled(True)
    calls = []
    monkeypatch.setattr(macros.subprocess, "Popen", lambda args: calls.append(args))

    macros.run_shell("echo hi")

    assert calls == []


def test_windows_minimize_does_not_run_xdotool_when_dry_run(monkeypatch):
    dry_run.set_enabled(True)
    calls = []
    monkeypatch.setattr(windows, "_list_window_ids", lambda: calls.append(True))

    windows.minimize_all_except_terminal()

    assert calls == []
