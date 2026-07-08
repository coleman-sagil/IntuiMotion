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
