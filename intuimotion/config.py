import yaml

from .actions import ACTION_MODULES
from .actions.macros import is_valid_key_name

DEFAULT_CONFIG_PATH = "config/gestures.yaml"


def load_config(path=DEFAULT_CONFIG_PATH):
    with open(path) as f:
        config = yaml.safe_load(f) or {}

    if not isinstance(config, dict):
        raise ValueError(
            f"gestures config must be a mapping of gesture name to action, got {type(config).__name__}"
        )

    for gesture, entry in config.items():
        _validate_entry(gesture, entry)

    return config


def _validate_entry(gesture, entry):
    if not isinstance(entry, dict):
        raise ValueError(f"gesture '{gesture}' must be a mapping, got {type(entry).__name__}")

    if "action" not in entry:
        raise ValueError(f"gesture '{gesture}' is missing an 'action' field")

    action = entry["action"]
    if action == "macro":
        _validate_macro_entry(gesture, entry)
    elif action in ACTION_MODULES:
        _validate_module_action(gesture, entry, action)
    else:
        known = ", ".join(sorted(list(ACTION_MODULES) + ["macro"]))
        raise ValueError(f"gesture '{gesture}' has unknown action '{action}' (expected one of: {known})")


def _validate_module_action(gesture, entry, action):
    if "function" not in entry:
        raise ValueError(f"gesture '{gesture}' (action: {action}) is missing a 'function' field")

    function_name = entry["function"]
    module = ACTION_MODULES[action]
    if (
        not isinstance(function_name, str)
        or function_name.startswith("_")
        or not hasattr(module, function_name)
    ):
        raise ValueError(
            f"gesture '{gesture}' references unknown function '{function_name}' for action '{action}'"
        )


def _validate_macro_entry(gesture, entry):
    macro_type = entry.get("type", "keys")
    if macro_type == "keys":
        keys = entry.get("keys")
        if not keys or not isinstance(keys, list):
            raise ValueError(f"gesture '{gesture}' (macro type: keys) needs a non-empty 'keys' list")
        for key in keys:
            if not isinstance(key, str) or not is_valid_key_name(key):
                raise ValueError(f"gesture '{gesture}' has an unrecognized key name '{key}' in 'keys'")
    elif macro_type == "shell":
        command = entry.get("command")
        if not command or not isinstance(command, str) or not command.strip():
            raise ValueError(f"gesture '{gesture}' (macro type: shell) needs a non-empty 'command' string")
    else:
        raise ValueError(
            f"gesture '{gesture}' has unknown macro type '{macro_type}' (expected 'keys' or 'shell')"
        )
