from .actions import macros, media, mouse

_ACTION_MODULES = {"mouse": mouse, "media": media}


class ActionDispatcher:
    def __init__(self, config):
        self.config = config

    def dispatch(self, gesture_name):
        entry = self.config.get(gesture_name)
        if entry is None:
            return

        action_type = entry["action"]
        if action_type == "macro":
            self._run_macro(entry)
            return

        module = _ACTION_MODULES.get(action_type)
        if module is None:
            return
        getattr(module, entry["function"])()

    def _run_macro(self, entry):
        macro_type = entry.get("type", "keys")
        if macro_type == "keys":
            macros.run_keys(entry["keys"])
        elif macro_type == "shell":
            macros.run_shell(entry["command"])
