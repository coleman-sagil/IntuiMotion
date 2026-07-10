from .actions import ACTION_MODULES, macros

# config.py validates every entry (action type known, function resolves,
# required keys present) before the app starts, so dispatch() can trust the
# shape of `entry` here rather than re-checking it on every gesture fire.


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

        module = ACTION_MODULES[action_type]
        getattr(module, entry["function"])()

    def _run_macro(self, entry):
        macro_type = entry.get("type", "keys")
        if macro_type == "keys":
            macros.run_keys(entry["keys"])
        elif macro_type == "shell":
            macros.run_shell(entry["command"])
