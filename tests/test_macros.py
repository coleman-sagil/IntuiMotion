from intuimotion.actions import macros


def test_is_valid_key_name_accepts_known_aliases():
    assert macros.is_valid_key_name("ctrl") is True
    assert macros.is_valid_key_name("CTRL") is True


def test_is_valid_key_name_accepts_single_characters():
    assert macros.is_valid_key_name("t") is True


def test_is_valid_key_name_rejects_unknown_multi_char_names():
    assert macros.is_valid_key_name("windows") is False


def test_run_keys_releases_already_pressed_keys_on_error(monkeypatch):
    pressed, released = [], []

    def fake_press(key):
        if key == "bad":
            raise ValueError(key)
        pressed.append(key)

    monkeypatch.setattr(macros._keyboard, "press", fake_press)
    monkeypatch.setattr(macros._keyboard, "release", lambda key: released.append(key))

    try:
        macros.run_keys(["ctrl", "shift", "bad"])
    except ValueError:
        pass

    assert pressed == [macros.KEY_ALIASES["ctrl"], macros.KEY_ALIASES["shift"]]
    assert released == list(reversed(pressed))


def test_run_shell_handles_bad_quoting_without_raising():
    macros.run_shell('echo "unbalanced')  # should not raise


def test_run_shell_handles_missing_executable_without_raising():
    macros.run_shell("this-command-does-not-exist-xyz")  # should not raise


def test_run_shell_does_nothing_for_blank_command():
    macros.run_shell("   ")  # should not raise, no subprocess started
