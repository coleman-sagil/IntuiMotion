import shlex
import subprocess
import sys

from pynput.keyboard import Controller as KeyboardController, Key

_keyboard = KeyboardController()

KEY_ALIASES = {
    "ctrl": Key.ctrl,
    "shift": Key.shift,
    "alt": Key.alt,
    "cmd": Key.cmd,
    "super": Key.cmd,
    "enter": Key.enter,
    "tab": Key.tab,
    "esc": Key.esc,
    "space": Key.space,
}


def is_valid_key_name(name):
    return name.lower() in KEY_ALIASES or len(name) == 1


def _resolve_key(name):
    return KEY_ALIASES.get(name.lower(), name)


def run_keys(keys):
    resolved = [_resolve_key(k) for k in keys]
    pressed = []
    try:
        for key in resolved:
            _keyboard.press(key)
            pressed.append(key)
    finally:
        for key in reversed(pressed):
            _keyboard.release(key)


def run_shell(command):
    # config.py validates `command` is a non-empty string at load time, but
    # bad quoting or a nonexistent executable can only be caught by actually
    # trying to run it, so those are handled here instead.
    try:
        args = shlex.split(command)
    except ValueError as error:
        print(f"macro shell command could not be parsed ({command!r}): {error}", file=sys.stderr)
        return

    if not args:
        return

    # shlex.split + no shell=True: config-file commands run as a literal
    # argv, not through a shell, so no injection risk from config content.
    try:
        subprocess.Popen(args)
    except OSError as error:
        print(f"macro shell command failed to start ({command!r}): {error}", file=sys.stderr)
