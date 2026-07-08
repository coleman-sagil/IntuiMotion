import yaml

DEFAULT_CONFIG_PATH = "config/gestures.yaml"


def load_config(path=DEFAULT_CONFIG_PATH):
    with open(path) as f:
        config = yaml.safe_load(f) or {}

    for gesture, entry in config.items():
        if "action" not in entry:
            raise ValueError(f"gesture '{gesture}' is missing an 'action' field")

    return config
