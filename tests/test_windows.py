from intuimotion.actions import windows


class _FakeResult:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_list_window_ids_parses_net_client_list(monkeypatch):
    fake_output = "_NET_CLIENT_LIST(WINDOW): window id # 0x1e00610, 0x1e00614, 0x2e0000a\n"
    monkeypatch.setattr(windows, "_run", lambda args: _FakeResult(fake_output))

    assert windows._list_window_ids() == ["0x1e00610", "0x1e00614", "0x2e0000a"]


def test_list_window_ids_empty_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(windows, "_run", lambda args: _FakeResult("", returncode=1))

    assert windows._list_window_ids() == []


def test_is_protected_matches_terminal_wm_class():
    output = 'WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal"\n'

    assert windows._is_protected(output) is True


def test_is_protected_false_for_non_terminal_wm_class():
    output = 'WM_CLASS(STRING) = "firefox", "Firefox"\n'

    assert windows._is_protected(output) is False


def test_minimize_all_except_terminal_skips_protected_windows(monkeypatch):
    monkeypatch.setattr(
        windows, "_list_window_ids", lambda: ["0x1", "0x2", "0x3"]
    )

    classes = {
        "0x1": 'WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal"\n',
        "0x2": 'WM_CLASS(STRING) = "firefox", "Firefox"\n',
        "0x3": 'WM_CLASS(STRING) = "code", "Code"\n',
    }
    monkeypatch.setattr(windows, "_window_class", lambda window_id: classes[window_id])

    minimized = []
    monkeypatch.setattr(
        windows.subprocess, "run", lambda args, **kwargs: minimized.append(args[-1])
    )

    windows.minimize_all_except_terminal()

    assert minimized == ["0x2", "0x3"]
