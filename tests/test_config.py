import textwrap

import pytest

from intuimotion.config import load_config


def test_load_config_parses_valid_yaml(tmp_path):
    config_file = tmp_path / "gestures.yaml"
    config_file.write_text(
        textwrap.dedent(
            """
            pinch:
              action: media
              function: play_pause
            """
        )
    )

    config = load_config(str(config_file))

    assert config["pinch"]["function"] == "play_pause"


def test_load_config_rejects_missing_action(tmp_path):
    config_file = tmp_path / "gestures.yaml"
    config_file.write_text(
        textwrap.dedent(
            """
            pinch:
              function: play_pause
            """
        )
    )

    with pytest.raises(ValueError):
        load_config(str(config_file))


def _write(tmp_path, content):
    config_file = tmp_path / "gestures.yaml"
    config_file.write_text(textwrap.dedent(content))
    return str(config_file)


def test_load_config_rejects_non_mapping_root(tmp_path):
    path = _write(tmp_path, "- a\n- b\n")

    with pytest.raises(ValueError):
        load_config(path)


def test_load_config_rejects_blank_gesture_body(tmp_path):
    path = _write(tmp_path, "pinch:\n")

    with pytest.raises(ValueError):
        load_config(path)


def test_load_config_rejects_scalar_gesture_body(tmp_path):
    path = _write(tmp_path, "pinch: action\n")

    with pytest.raises(ValueError):
        load_config(path)


def test_load_config_rejects_unknown_action_type(tmp_path):
    path = _write(tmp_path, "pinch:\n  action: keyboard\n  function: play_pause\n")

    with pytest.raises(ValueError):
        load_config(path)


def test_load_config_rejects_missing_function(tmp_path):
    path = _write(tmp_path, "pinch:\n  action: media\n")

    with pytest.raises(ValueError):
        load_config(path)


def test_load_config_rejects_unknown_function_name(tmp_path):
    path = _write(tmp_path, "pinch:\n  action: media\n  function: play_puase\n")

    with pytest.raises(ValueError):
        load_config(path)


def test_load_config_rejects_private_function_name(tmp_path):
    path = _write(tmp_path, "pinch:\n  action: mouse\n  function: _clamp\n")

    with pytest.raises(ValueError):
        load_config(path)


def test_load_config_rejects_macro_keys_missing_keys(tmp_path):
    path = _write(tmp_path, "pinch:\n  action: macro\n  type: keys\n")

    with pytest.raises(ValueError):
        load_config(path)


def test_load_config_rejects_macro_with_bad_key_name(tmp_path):
    path = _write(tmp_path, 'pinch:\n  action: macro\n  type: keys\n  keys: ["ctrl", "windows"]\n')

    with pytest.raises(ValueError):
        load_config(path)


def test_load_config_accepts_macro_keys_with_valid_names(tmp_path):
    path = _write(tmp_path, 'pinch:\n  action: macro\n  type: keys\n  keys: ["ctrl", "shift", "t"]\n')

    config = load_config(path)

    assert config["pinch"]["keys"] == ["ctrl", "shift", "t"]


def test_load_config_rejects_macro_shell_missing_command(tmp_path):
    path = _write(tmp_path, "pinch:\n  action: macro\n  type: shell\n")

    with pytest.raises(ValueError):
        load_config(path)


def test_load_config_rejects_macro_shell_blank_command(tmp_path):
    path = _write(tmp_path, 'pinch:\n  action: macro\n  type: shell\n  command: "   "\n')

    with pytest.raises(ValueError):
        load_config(path)


def test_load_config_accepts_macro_shell_with_command(tmp_path):
    path = _write(tmp_path, 'pinch:\n  action: macro\n  type: shell\n  command: "notify-send hi"\n')

    config = load_config(path)

    assert config["pinch"]["command"] == "notify-send hi"


def test_load_config_rejects_unknown_macro_type(tmp_path):
    path = _write(tmp_path, "pinch:\n  action: macro\n  type: key\n  keys: [a]\n")

    with pytest.raises(ValueError):
        load_config(path)
